"""
The worker: claims jobs from the PostgreSQL queue and runs them.

Run one (or several, on any machine that reaches the database):

    python -m app.worker

or set RUN_EMBEDDED_WORKER=true to run a single worker thread inside the API
process (handy for a one-process deployment). Ctrl+C / SIGTERM lets the current
job finish before the worker exits.
"""
import logging
import os
import socket
import tempfile
import threading
import time
import uuid
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.core import metrics
from app.core.config import settings
from app.db.models import Document, Job
from app.db.session import SessionLocal
from app.jobs import queue
from app.jobs.queue import JobCancelled, PermanentJobError

logger = logging.getLogger(__name__)

STALE_CHECK_EVERY_SECONDS = 60


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


# ------------------------------------------------------------------ handlers
def run_ingest_job(db: Session, job: Job) -> None:
    """Writes the stored upload to a temp file and runs the normal ingestion pipeline."""
    from app.rag.pipeline import ingest_document

    document = db.get(Document, job.document_id) if job.document_id else None
    if document is None or document.deleted_at is not None:
        raise JobCancelled("The document was deleted before it was processed")
    if job.file_data is None:
        raise PermanentJobError("The uploaded file is no longer stored")

    payload = job.payload or {}
    ext = document.filename.lower().rsplit(".", 1)[-1] if "." in document.filename else "bin"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp_path = tmp.name
            tmp.write(job.file_data)
        document = ingest_document(
            db, tmp_path, document.filename,
            strategy=payload.get("strategy", "fixed_size"),
            chunk_size=int(payload.get("chunk_size", 500)),
            overlap=int(payload.get("overlap", 0)),
            document=document,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    if document.status == "failed":
        notes = (document.ingest_report or {}).get("notes") or []
        raise PermanentJobError("Document processing failed" + (f": {notes[0]}" if notes else ""))


HANDLERS: Dict[str, Callable[[Session, Job], None]] = {
    "ingest": run_ingest_job,
}


def _mark_document_failed(db: Session, job: Job, message: str) -> None:
    if not job.document_id:
        return
    document = db.get(Document, job.document_id)
    if document is not None and document.deleted_at is None and document.status != "failed":
        document.status = "failed"
        report = dict(document.ingest_report or {})
        report["notes"] = [message[:300]] + list(report.get("notes") or [])
        document.ingest_report = report
        db.commit()


# -------------------------------------------------------------------- worker
class Worker:
    def __init__(self, worker_id: Optional[str] = None,
                 session_factory: Callable[[], Session] = SessionLocal,
                 handlers: Optional[Dict[str, Callable[[Session, Job], None]]] = None):
        self.worker_id = worker_id or default_worker_id()
        self.session_factory = session_factory
        self.handlers = handlers if handlers is not None else HANDLERS
        self._last_stale_check = 0.0

    def _maybe_requeue_stale(self) -> None:
        now = time.monotonic()
        if now - self._last_stale_check < STALE_CHECK_EVERY_SECONDS:
            return
        self._last_stale_check = now
        db = self.session_factory()
        try:
            queue.requeue_stale(db)
        finally:
            db.close()

    def run_once(self) -> Optional[str]:
        """Claims and runs at most one job. Returns its final status, or None if the queue was empty."""
        self._maybe_requeue_stale()

        db = self.session_factory()
        try:
            job_id = queue.claim(db, self.worker_id)
        finally:
            db.close()
        if job_id is None:
            return None

        db = self.session_factory()
        started = time.perf_counter()
        try:
            job = db.get(Job, job_id)
            handler = self.handlers.get(job.kind)
            logger.info("Job %s (%s) started, attempt %s/%s", job.id, job.kind, job.attempts, job.max_attempts)
            try:
                if handler is None:
                    raise PermanentJobError(f"No handler for job kind {job.kind!r}")
                handler(db, job)
            except JobCancelled as exc:
                db.rollback()
                queue.cancel(db, db.get(Job, job_id), str(exc))
            except PermanentJobError as exc:
                db.rollback()
                job = db.get(Job, job_id)
                queue.fail(db, job, str(exc), retryable=False)
                _mark_document_failed(db, job, str(exc))
            except Exception as exc:  # unexpected: retry with backoff
                logger.exception("Job %s failed", job_id)
                db.rollback()
                job = db.get(Job, job_id)
                status = queue.fail(db, job, f"{type(exc).__name__}: {exc}", retryable=True)
                if status == "failed":
                    _mark_document_failed(db, job, f"Processing failed: {type(exc).__name__}")
            else:
                queue.complete(db, job)

            final = db.get(Job, job_id).status
            elapsed = time.perf_counter() - started
            metrics.JOBS_FINISHED.inc(kind=job.kind, status=final)
            metrics.JOB_SECONDS.observe(elapsed, kind=job.kind)
            logger.info("Job %s finished: %s in %.1fs", job_id, final, elapsed)
            return final
        finally:
            db.close()

    def run_forever(self, stop: threading.Event) -> None:
        logger.info("Worker %s started", self.worker_id)
        while not stop.is_set():
            try:
                status = self.run_once()
            except Exception:  # the database went away, etc.: wait and keep going
                logger.exception("Worker loop error")
                status = None
            if status is None:
                stop.wait(settings.WORKER_POLL_SECONDS)
        logger.info("Worker %s stopped", self.worker_id)


# ------------------------------------------------------- embedded (in-API) mode
_embedded_stop: Optional[threading.Event] = None
_embedded_thread: Optional[threading.Thread] = None


def start_embedded_worker() -> None:
    global _embedded_stop, _embedded_thread
    if _embedded_thread is not None and _embedded_thread.is_alive():
        return
    _embedded_stop = threading.Event()
    worker = Worker()
    _embedded_thread = threading.Thread(target=worker.run_forever, args=(_embedded_stop,),
                                        name="kf-embedded-worker", daemon=True)
    _embedded_thread.start()


def stop_embedded_worker(timeout: float = 30.0) -> None:
    global _embedded_thread
    if _embedded_stop is not None:
        _embedded_stop.set()
    if _embedded_thread is not None:
        _embedded_thread.join(timeout)
        _embedded_thread = None
