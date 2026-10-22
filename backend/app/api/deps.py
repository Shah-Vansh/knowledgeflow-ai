from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import Workspace
from app.db.session import SessionLocal

DEFAULT_WORKSPACE_ID = 1  # "General": created by migration 0005, cannot be deleted


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_workspace(db: Session, workspace_id: int) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace