"""
A small job queue in PostgreSQL (Phase 16).

Why the database and not Redis/Celery: the project already depends on PostgreSQL,
jobs need to be transactional with the rows they create, and the load is a few
uploads a minute. `FOR UPDATE SKIP LOCKED` lets any number of workers claim jobs
concurrently: a row another worker has locked is skipped instead of waited on, so
no job is handed out twice.

Life of a job:
    queued --claim--> running --complete--> succeeded
                         |----fail (attempts left)--> queued (run_after = now + backoff)
                         |----fail (no attempts left / permanent)--> failed
    running for longer than JOB_STALE_AFTER_SECONDS (worker crashed) --requeue_stale--> queued / failed
    queued/running whose document was deleted --> cancelled
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Job

logger = logging.getLogger(__name__)

STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
TERMINAL = {"succeeded", "failed", "cancelled"}
MAX_ERROR_LENGTH = 2000

_CLAIM_SQL = text(
    """
    UPDATE jobs
       SET status = 'running',
           attempts = attempts + 1,
           locked_by = :worker,
           locked_at = now(),
           started_at = COALESCE(started_at, now())
     WHERE id = (
            SELECT id FROM jobs
             WHERE status = 'queued' AND run_after <= now()
             ORDER BY run_after, id
             LIMIT 1
             FOR UPDATE SKIP LOCKED
           )
    RETURNING id
    """
)


class PermanentJobError(Exception):
    """The job can never succeed (e.g. the file can't be read): don't retry it."""


class JobCancelled(PermanentJobError):
    """The job's subject is gone (e.g. the document was deleted): stop quietly."""


def backoff_seconds(attempt: int) -> int:
    """10s, 20s, 40s, ... (base * 2^(attempt-1)), capped at one hour."""
    attempt = max(1, attempt)
    return min(3600, settings.JOB_RETRY_BASE_SECONDS * (2 ** (attempt - 1)))


def enqueue(db: Session, kind: str, workspace_id: int, payload: Optional[dict] = None,
            document_id: Optional[int] = None, file_data: Optional[bytes] = None,
            max_attempts: Optional[int] = None) -> Job:
    """Adds a queued job to the session. The CALLER commits, so the job and the
    rows it belongs to (e.g. the document) appear together or not at all."""
    job = Job(
        kind=kind,
        status="queued",
        workspace_id=workspace_id,
        document_id=document_id,
        payload=payload or {},
        file_data=file_data,
        max_attempts=max_attempts or settings.JOB_MAX_ATTEMPTS,
    )
    db.add(job)
    db.flush()
    return job


def claim(db: Session, worker_id: str) -> Optional[int]:
    """Atomically takes the oldest runnable job. Returns its id, or None when there is none."""
    job_id = db.execute(_CLAIM_SQL, {"worker": worker_id[:128]}).scalar()
    db.commit()
    return job_id


def _finish(job: Job, status: str, error: Optional[str] = None) -> None:
    job.status = status
    job.finished_at = datetime.now(timezone.utc)
    job.locked_by = None
    job.locked_at = None
    job.file_data = None  # the upload bytes are only needed until the job is over
    if error is not None:
        job.last_error = error[:MAX_ERROR_LENGTH]


def complete(db: Session, job: Job) -> None:
    _finish(job, "succeeded")
    db.commit()


def cancel(db: Session, job: Job, reason: str) -> None:
    _finish(job, "cancelled", reason)
    db.commit()


def fail(db: Session, job: Job, error: str, retryable: bool = True) -> str:
    """Records a failed attempt. Returns the new status ("queued" for a retry, or "failed")."""
    if retryable and job.attempts < job.max_attempts:
        job.status = "queued"
        job.locked_by = None
        job.locked_at = None
        job.last_error = error[:MAX_ERROR_LENGTH]
        job.run_after = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds(job.attempts))
    else:
        _finish(job, "failed", error)
    db.commit()
    return job.status


def requeue_stale(db: Session, older_than_seconds: Optional[int] = None) -> int:
    """
    A job stays "running" forever if its worker died mid-way. Puts such jobs back in
    the queue (or fails them when they've used every attempt). Returns how many.
    """
    seconds = older_than_seconds if older_than_seconds is not None else settings.JOB_STALE_AFTER_SECONDS
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    stale = (
        db.query(Job)
        .filter(Job.status == "running", Job.locked_at < cutoff)
        .with_for_update(skip_locked=True)
        .all()
    )
    message = "The worker stopped before finishing this job"
    for job in stale:
        if job.attempts < job.max_attempts:
            job.status = "queued"
            job.locked_by = None
            job.locked_at = None
            job.last_error = message
            job.run_after = datetime.now(timezone.utc)
        else:
            _finish(job, "failed", message)
    db.commit()
    if stale:
        logger.warning("Requeued or failed %d stale job(s)", len(stale))
    return len(stale)


def queue_stats(db: Session) -> Dict[str, object]:
    """Counts per status and the age of the oldest runnable job (for /metrics)."""
    counts = {status: 0 for status in STATUSES}
    for status, count in db.query(Job.status, func.count(Job.id)).group_by(Job.status).all():
        counts[status] = count
    oldest = (
        db.query(func.min(Job.created_at))
        .filter(Job.status == "queued")
        .scalar()
    )
    age = (datetime.now(timezone.utc) - oldest).total_seconds() if oldest else 0.0
    return {"counts": counts, "oldest_queued_seconds": max(0.0, age)}


def job_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "workspace_id": job.workspace_id,
        "document_id": job.document_id,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "last_error": job.last_error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "run_after": job.run_after.isoformat() if job.run_after else None,
    }
