"""
The PostgreSQL job queue and the worker (Phase 16), against the real test database.

  * claiming skips rows another worker has locked (SKIP LOCKED) instead of waiting;
  * concurrent workers never get the same job;
  * retries back off, stop at max_attempts, permanent errors are not retried;
  * jobs left "running" by a dead worker are requeued (or failed);
  * an async upload is processed end to end by the worker with the real embedder.
"""
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.db.models import Chunk, Document, Job, Workspace
from app.db.session import SessionLocal, engine
from app.jobs import queue
from app.jobs.worker import Worker, run_ingest_job
from app.main import app
from tests.auth_helpers import delete_workspaces

client = TestClient(app)

TEXT = (b"KnowledgeFlow queue test. The quarterly report says revenue grew in the north region. "
        b"The worker embeds this text and stores it as chunks.")


@pytest.fixture
def ws():
    """A fresh workspace; no jobs left anywhere before or after the test."""
    db = SessionLocal()
    db.query(Job).delete()
    workspace = Workspace(name=f"jobs-{uuid.uuid4().hex[:8]}")
    db.add(workspace)
    db.commit()
    workspace_id = workspace.id
    db.close()
    yield workspace_id
    db = SessionLocal()
    db.query(Job).delete()
    delete_workspaces(db, [workspace_id])
    db.commit()
    db.close()


def _doc(db, workspace_id, status="queued", filename="q.txt"):
    document = Document(filename=filename, status=status, workspace_id=workspace_id, source_type="txt")
    db.add(document)
    db.flush()
    return document


def _enqueue(workspace_id, n=1, file_data=TEXT, max_attempts=3):
    db = SessionLocal()
    ids = []
    for _ in range(n):
        document = _doc(db, workspace_id)
        job = queue.enqueue(db, "ingest", workspace_id, payload={"chunk_size": 200},
                            document_id=document.id, file_data=file_data, max_attempts=max_attempts)
        ids.append(job.id)
    db.commit()
    db.close()
    return ids


def _job(job_id) -> Job:
    db = SessionLocal()
    job = db.get(Job, job_id)
    db.expunge(job)
    db.close()
    return job


def _make_runnable(job_id):
    db = SessionLocal()
    db.query(Job).filter(Job.id == job_id).update({"run_after": datetime.now(timezone.utc) - timedelta(seconds=1)})
    db.commit()
    db.close()


# ------------------------------------------------------------------ claiming
def test_claim_takes_oldest_and_marks_running(ws):
    first, second = _enqueue(ws, 2)
    db = SessionLocal()
    assert queue.claim(db, "w1") == first
    db.close()
    job = _job(first)
    assert job.status == "running" and job.attempts == 1 and job.locked_by == "w1"
    assert job.locked_at is not None and job.started_at is not None
    assert _job(second).status == "queued"


def test_claim_returns_none_when_empty(ws):
    db = SessionLocal()
    assert queue.claim(db, "w1") is None
    db.close()


def test_claim_skips_a_row_locked_by_another_worker_instead_of_waiting(ws):
    first, second = _enqueue(ws, 2)
    holder = engine.connect()
    tx = holder.begin()
    locked = holder.execute(text("SELECT id FROM jobs WHERE id = :id FOR UPDATE"), {"id": first}).scalar()
    assert locked == first
    try:
        db = SessionLocal()
        db.execute(text("SET lock_timeout = '2s'"))  # without SKIP LOCKED this would error out
        started = time.perf_counter()
        claimed = queue.claim(db, "w2")
        db.close()
        assert claimed == second
        assert time.perf_counter() - started < 1.5
    finally:
        tx.rollback()
        holder.close()
    assert _job(first).status == "queued"


def test_concurrent_workers_never_share_a_job(ws):
    ids = set(_enqueue(ws, 24, file_data=b"x"))
    claimed, errors = [], []
    lock = threading.Lock()

    def drain(name):
        try:
            while True:
                db = SessionLocal()
                try:
                    job_id = queue.claim(db, name)
                finally:
                    db.close()
                if job_id is None:
                    return
                with lock:
                    claimed.append(job_id)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=drain, args=(f"w{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors
    assert len(claimed) == len(set(claimed)) == 24
    assert set(claimed) == ids


def test_a_job_scheduled_for_later_is_not_claimed(ws):
    (job_id,) = _enqueue(ws)
    db = SessionLocal()
    db.query(Job).filter(Job.id == job_id).update({"run_after": datetime.now(timezone.utc) + timedelta(hours=1)})
    db.commit()
    assert queue.claim(db, "w1") is None
    db.close()


# ------------------------------------------------------------------ retries
def test_backoff_doubles_and_is_capped(monkeypatch):
    monkeypatch.setattr(settings, "JOB_RETRY_BASE_SECONDS", 10)
    assert [queue.backoff_seconds(a) for a in (1, 2, 3, 4)] == [10, 20, 40, 80]
    assert queue.backoff_seconds(30) == 3600


def test_retryable_failure_requeues_with_backoff_then_fails_at_max(ws):
    (job_id,) = _enqueue(ws, max_attempts=2)
    db = SessionLocal()
    assert queue.claim(db, "w1") == job_id
    job = db.get(Job, job_id)
    assert queue.fail(db, job, "boom 1") == "queued"
    job = db.get(Job, job_id)
    assert job.locked_by is None and job.last_error == "boom 1"
    assert job.run_after > datetime.now(timezone.utc) + timedelta(seconds=5)
    assert job.file_data is not None                 # still needed for the retry
    assert queue.claim(db, "w1") is None             # not before its backoff

    _make_runnable(job_id)
    assert queue.claim(db, "w1") == job_id
    job = db.get(Job, job_id)
    db.refresh(job)
    assert job.attempts == 2
    assert queue.fail(db, job, "boom 2") == "failed"
    job = db.get(Job, job_id)
    assert job.status == "failed" and job.finished_at is not None
    assert job.file_data is None and job.last_error == "boom 2"
    db.close()


def test_permanent_failure_is_not_retried(ws):
    (job_id,) = _enqueue(ws, max_attempts=5)
    db = SessionLocal()
    queue.claim(db, "w1")
    assert queue.fail(db, db.get(Job, job_id), "bad file", retryable=False) == "failed"
    db.close()
    assert _job(job_id).attempts == 1


def test_stale_running_jobs_are_requeued_or_failed(ws):
    keep, exhausted, fresh = _enqueue(ws, 3)
    long_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    db = SessionLocal()
    db.query(Job).filter(Job.id == keep).update({"status": "running", "locked_at": long_ago, "attempts": 1})
    db.query(Job).filter(Job.id == exhausted).update({"status": "running", "locked_at": long_ago, "attempts": 3})
    db.query(Job).filter(Job.id == fresh).update({"status": "running",
                                                  "locked_at": datetime.now(timezone.utc), "attempts": 1})
    db.commit()
    assert queue.requeue_stale(db, older_than_seconds=900) == 2
    db.close()
    assert _job(keep).status == "queued" and _job(keep).locked_by is None
    assert _job(exhausted).status == "failed" and _job(exhausted).file_data is None
    assert _job(fresh).status == "running"


def test_queue_stats_counts_and_oldest_age(ws):
    _enqueue(ws, 2)
    db = SessionLocal()
    db.query(Job).update({"created_at": datetime.now(timezone.utc) - timedelta(seconds=120)})
    db.commit()
    stats = queue.queue_stats(db)
    db.close()
    assert stats["counts"]["queued"] == 2 and stats["counts"]["running"] == 0
    assert 100 < stats["oldest_queued_seconds"] < 1000


# ------------------------------------------------------------------ worker
def test_worker_processes_an_ingest_job_with_the_real_embedder(ws):
    (job_id,) = _enqueue(ws)
    assert Worker("t1").run_once() == "succeeded"
    job = _job(job_id)
    assert job.status == "succeeded" and job.file_data is None and job.finished_at is not None
    db = SessionLocal()
    document = db.get(Document, job.document_id)
    assert document.status == "processed"
    assert db.query(Chunk).filter(Chunk.document_id == document.id).count() >= 1
    db.close()
    assert Worker("t1").run_once() is None  # queue drained


def test_worker_retries_unexpected_errors_then_marks_the_document_failed(ws):
    (job_id,) = _enqueue(ws, max_attempts=2)

    def explode(db, job):
        raise RuntimeError("database hiccup")

    worker = Worker("t2", handlers={"ingest": explode})
    assert worker.run_once() == "queued"
    assert _job(job_id).attempts == 1 and "database hiccup" in _job(job_id).last_error
    _make_runnable(job_id)
    assert worker.run_once() == "failed"
    db = SessionLocal()
    document = db.get(Document, _job(job_id).document_id)
    assert document.status == "failed"
    assert any("RuntimeError" in note for note in document.ingest_report["notes"])
    db.close()


def test_unreadable_content_fails_once_without_retry(ws):
    (job_id,) = _enqueue(ws, file_data=b"   \n\n   ", max_attempts=3)
    assert Worker("t3").run_once() == "failed"
    job = _job(job_id)
    assert job.attempts == 1 and "processing failed" in job.last_error.lower()


def test_job_for_a_deleted_document_is_cancelled(ws):
    (job_id,) = _enqueue(ws)
    db = SessionLocal()
    document = db.get(Document, _job(job_id).document_id)
    document.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.close()
    assert Worker("t4").run_once() == "cancelled"
    assert _job(job_id).file_data is None


def test_retry_removes_chunks_from_an_interrupted_attempt(ws):
    (job_id,) = _enqueue(ws)
    db = SessionLocal()
    job = db.get(Job, job_id)
    run_ingest_job(db, job)                      # first attempt "crashed" after writing chunks
    first = db.query(Chunk).filter(Chunk.document_id == job.document_id).count()
    run_ingest_job(db, db.get(Job, job_id))      # the retry starts clean
    second = db.query(Chunk).filter(Chunk.document_id == job.document_id).count()
    db.close()
    assert first >= 1 and second == first


def test_embedded_worker_thread_drains_the_queue(ws, monkeypatch):
    from app.jobs import worker as worker_module

    monkeypatch.setattr(settings, "WORKER_POLL_SECONDS", 0.2)
    (job_id,) = _enqueue(ws)
    worker_module.start_embedded_worker()
    try:
        deadline = time.time() + 60
        while time.time() < deadline and _job(job_id).status not in queue.TERMINAL:
            time.sleep(0.2)
    finally:
        worker_module.stop_embedded_worker(timeout=30)
    assert _job(job_id).status == "succeeded"


# ------------------------------------------------------------------ API
def test_async_upload_returns_202_and_the_worker_finishes_it(ws, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_ASYNC", True)
    response = client.post("/documents/upload",
                           files={"file": ("queued.txt", TEXT, "text/plain")},
                           data={"workspace_id": str(ws), "chunk_size": "200"})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued" and body["job_id"] and body["ingest_report"] is None

    job = client.get(f"/jobs/{body['job_id']}").json()
    assert job["status"] == "queued" and job["document"]["status"] == "queued"
    assert "file_data" not in job
    assert _job(body["job_id"]).payload == {"strategy": "fixed_size", "chunk_size": 200, "overlap": 0}

    assert Worker("api").run_once() == "succeeded"
    job = client.get(f"/jobs/{body['job_id']}").json()
    assert job["status"] == "succeeded" and job["document"]["status"] == "processed"
    assert job["document"]["ingest_report"] is not None
    listed = client.get(f"/jobs?workspace_id={ws}").json()
    assert [j["id"] for j in listed] == [body["job_id"]]


def test_async_upload_still_validates_before_queueing(ws, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_ASYNC", True)
    response = client.post("/documents/upload",
                           files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
                           data={"workspace_id": str(ws)})
    assert response.status_code == 400
    db = SessionLocal()
    assert db.query(Job).count() == 0
    db.close()


def test_sync_upload_is_unchanged_and_has_no_job(ws):
    response = client.post("/documents/upload",
                           files={"file": ("sync.txt", TEXT, "text/plain")},
                           data={"workspace_id": str(ws)})
    assert response.status_code == 200
    assert response.json()["status"] == "processed" and response.json()["job_id"] is None


def test_missing_job_is_404(ws):
    assert client.get("/jobs/2000000000").status_code == 404


def test_deleting_the_workspace_removes_its_jobs(ws):
    (job_id,) = _enqueue(ws)
    db = SessionLocal()
    delete_workspaces(db, [ws])
    db.commit()
    assert db.get(Job, job_id) is None
    db.close()
