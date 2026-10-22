from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import DEFAULT_WORKSPACE_ID, get_db, require_workspace
from app.db.models import Document, Workspace

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)


def _workspace_dict(workspace: Workspace, document_count: int) -> dict:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "description": workspace.description,
        "document_count": document_count,
        "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
    }


@router.get("")
def list_workspaces(db: Session = Depends(get_db)):
    rows = (
        db.query(Workspace, func.count(Document.id))
        .outerjoin(
            Document,
            and_(Document.workspace_id == Workspace.id, Document.deleted_at.is_(None)),
        )
        .group_by(Workspace.id)
        .order_by(Workspace.id)
        .all()
    )
    return [_workspace_dict(workspace, count) for workspace, count in rows]


@router.post("", status_code=201)
def create_workspace(request: WorkspaceCreate, db: Session = Depends(get_db)):
    name = " ".join(request.name.split())
    if not name:
        raise HTTPException(status_code=422, detail="Workspace name must not be empty")

    existing = db.query(Workspace).filter(func.lower(Workspace.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail="A workspace with this name already exists")

    workspace = Workspace(name=name, description=(request.description or "").strip() or None)
    db.add(workspace)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A workspace with this name already exists")

    db.refresh(workspace)
    return _workspace_dict(workspace, 0)


@router.delete("/{workspace_id}")
def delete_workspace(workspace_id: int, db: Session = Depends(get_db)):
    if workspace_id == DEFAULT_WORKSPACE_ID:
        raise HTTPException(status_code=400, detail="The default workspace cannot be deleted")

    require_workspace(db, workspace_id)

    active = (
        db.query(func.count(Document.id))
        .filter(Document.workspace_id == workspace_id, Document.deleted_at.is_(None))
        .scalar()
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"Workspace still has {active} document(s); delete them first",
        )

    # Soft-deleted documents hold no chunks; remove their rows so the foreign key
    # doesn't block deleting the workspace. Conversations cascade in the database.
    db.query(Document).filter(Document.workspace_id == workspace_id).delete(
        synchronize_session=False
    )
    db.query(Workspace).filter(Workspace.id == workspace_id).delete(synchronize_session=False)
    db.commit()

    return {"workspace_id": workspace_id, "deleted": True}