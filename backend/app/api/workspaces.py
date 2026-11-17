from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import DEFAULT_WORKSPACE_ID, get_db, require_workspace
from app.core.access import ROLES, current_user
from app.core.security import normalize_email
from app.db.models import Document, User, Workspace, WorkspaceMember

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

LAST_OWNER = "A workspace needs at least one owner"


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)


class MemberAdd(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = "viewer"


def _workspace_dict(workspace: Workspace, document_count: int, role: Optional[str] = None) -> dict:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "description": workspace.description,
        "document_count": document_count,
        "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
        "role": role,
    }


@router.get("")
def list_workspaces(request: Request, db: Session = Depends(get_db)):
    """With auth on: only the caller's workspaces, each with the caller's role."""
    user = current_user(request)
    doc_count = func.count(Document.id)
    query = db.query(Workspace, doc_count).outerjoin(
        Document, and_(Document.workspace_id == Workspace.id, Document.deleted_at.is_(None))
    )
    if user is not None:
        query = (
            db.query(Workspace, doc_count, WorkspaceMember.role)
            .join(WorkspaceMember, and_(WorkspaceMember.workspace_id == Workspace.id,
                                        WorkspaceMember.user_id == user.id))
            .outerjoin(Document, and_(Document.workspace_id == Workspace.id, Document.deleted_at.is_(None)))
            .group_by(Workspace.id, WorkspaceMember.role)
            .order_by(Workspace.id)
        )
        return [_workspace_dict(w, count, role) for w, count, role in query.all()]
    rows = query.group_by(Workspace.id).order_by(Workspace.id).all()
    return [_workspace_dict(w, count) for w, count in rows]


@router.post("", status_code=201)
def create_workspace(payload: WorkspaceCreate, request: Request, db: Session = Depends(get_db)):
    name = " ".join(payload.name.split())
    if not name:
        raise HTTPException(status_code=422, detail="Workspace name must not be empty")

    existing = db.query(Workspace).filter(func.lower(Workspace.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail="A workspace with this name already exists")

    user = current_user(request)
    workspace = Workspace(name=name, description=(payload.description or "").strip() or None)
    db.add(workspace)
    try:
        db.flush()
        if user is not None:  # creator becomes owner in the SAME commit
            db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A workspace with this name already exists")

    db.refresh(workspace)
    return _workspace_dict(workspace, 0, "owner" if user is not None else None)


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
    # doesn't block deleting the workspace. Conversations and members cascade.
    db.query(Document).filter(Document.workspace_id == workspace_id).delete(
        synchronize_session=False
    )
    db.query(Workspace).filter(Workspace.id == workspace_id).delete(synchronize_session=False)
    db.commit()

    return {"workspace_id": workspace_id, "deleted": True}


# ------------------------------------------------------------------ members
def _member_dict(member: WorkspaceMember, user: User) -> dict:
    return {
        "user_id": user.id,
        "email": user.email,
        "role": member.role,
        "added_at": member.created_at.isoformat() if member.created_at else None,
    }


def _owner_count(db: Session, workspace_id: int) -> int:
    return (
        db.query(func.count(WorkspaceMember.user_id))
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
        .scalar()
    )


@router.get("/{workspace_id}/members")
def list_members(workspace_id: int, db: Session = Depends(get_db)):
    require_workspace(db, workspace_id)
    rows = (
        db.query(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .order_by(User.email)
        .all()
    )
    return [_member_dict(m, u) for m, u in rows]


@router.post("/{workspace_id}/members", status_code=201)
def add_member(workspace_id: int, payload: MemberAdd, db: Session = Depends(get_db)):
    """Adds a registered user, or changes the role of an existing member."""
    require_workspace(db, workspace_id)
    role = payload.role.strip().lower()
    if role not in ROLES:
        raise HTTPException(status_code=422, detail=f"Role must be one of {', '.join(ROLES)}")
    try:
        email = normalize_email(payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    user = db.query(User).filter(User.email == email, User.is_active.is_(True)).first()
    if user is None:
        raise HTTPException(status_code=404, detail="No registered user with this email")

    member = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user.id})
    if member is None:
        member = WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=role)
        db.add(member)
    else:
        if member.role == "owner" and role != "owner" and _owner_count(db, workspace_id) <= 1:
            raise HTTPException(status_code=409, detail=LAST_OWNER)
        member.role = role
    db.commit()
    db.refresh(member)
    return _member_dict(member, user)


@router.delete("/{workspace_id}/members/{user_id}")
def remove_member(workspace_id: int, user_id: int, db: Session = Depends(get_db)):
    require_workspace(db, workspace_id)
    member = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
    if member is None:
        raise HTTPException(status_code=404, detail="Not a member of this workspace")
    if member.role == "owner" and _owner_count(db, workspace_id) <= 1:
        raise HTTPException(status_code=409, detail=LAST_OWNER)
    db.delete(member)
    db.commit()
    return {"workspace_id": workspace_id, "user_id": user_id, "removed": True}
