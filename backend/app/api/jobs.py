"""Background job status (Phase 16): the upload page polls GET /jobs/{job_id}."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_workspace
from app.db.models import Document, Job
from app.jobs.queue import job_dict

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _with_document(db: Session, job: Job) -> dict:
    data = job_dict(job)
    document = db.get(Document, job.document_id) if job.document_id else None
    data["document"] = None if document is None or document.deleted_at is not None else {
        "id": document.id,
        "filename": document.filename,
        "status": document.status,
        "ingest_report": document.ingest_report,
    }
    return data


@router.get("")
def list_jobs(workspace_id: int = Query(...), limit: int = Query(50, ge=1, le=200),
              db: Session = Depends(get_db)):
    require_workspace(db, workspace_id)
    jobs = (
        db.query(Job)
        .filter(Job.workspace_id == workspace_id)
        .order_by(Job.id.desc())
        .limit(limit)
        .all()
    )
    return [job_dict(job) for job in jobs]


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _with_document(db, job)
