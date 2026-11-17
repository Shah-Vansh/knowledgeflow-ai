"""Registration, login and the current user (Phase 15)."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.access import (AuthUser, bearer_token, check_rate_limit, current_user)
from app.core.config import settings
from app.core.security import (TokenError, create_access_token, decode_access_token,
                               hash_password, needs_rehash, normalize_email,
                               validate_password, verify_dummy, verify_password)
from app.db.models import User, Workspace, WorkspaceMember

router = APIRouter(prefix="/auth", tags=["auth"])

_REGISTRATION_LOCK = 815_015  # pg_advisory_xact_lock key: serializes the first-user claim
GENERIC_LOGIN_FAILURE = "Invalid email or password"


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def _token_response(user: User) -> dict:
    return {
        "access_token": create_access_token(user.id, user.email, version=user.token_version or 0),
        "token_type": "bearer",
        "expires_in": settings.JWT_EXPIRE_MINUTES * 60,
        "user": _user_dict(user),
    }


def _require_secret() -> None:
    if not settings.JWT_SECRET:
        raise HTTPException(status_code=503, detail="Authentication is not configured (JWT_SECRET is empty)")


@router.get("/config")
def auth_config(db: Session = Depends(get_db)):
    has_users = db.query(User.id).first() is not None
    return {
        "auth_required": settings.AUTH_REQUIRED,
        "registration_open": settings.REGISTRATION_OPEN or not has_users,
        "password_min_length": settings.PASSWORD_MIN_LENGTH,
    }


@router.post("/register", status_code=201)
def register(request: Credentials, db: Session = Depends(get_db)):
    """
    The FIRST user can always register and becomes owner of every existing workspace
    (that's how a single-user install is claimed). Later users need REGISTRATION_OPEN
    and start with no workspaces until an owner adds them.
    """
    _require_secret()
    try:
        email = normalize_email(request.email)
        validate_password(request.password, email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    password_hash = hash_password(request.password)

    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _REGISTRATION_LOCK})
    is_first = db.query(func.count(User.id)).scalar() == 0
    if not is_first and not settings.REGISTRATION_OPEN:
        db.rollback()
        raise HTTPException(status_code=403, detail="Registration is closed; ask a workspace owner")
    if db.query(User.id).filter(User.email == email).first() is not None:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(email=email, password_hash=password_hash, is_active=True)
    db.add(user)
    try:
        db.flush()
        if is_first:
            for (workspace_id,) in db.query(Workspace.id).all():
                db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role="owner"))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    db.refresh(user)
    return {**_token_response(user), "claimed_existing_workspaces": is_first}


@router.post("/login")
def login(request: Credentials, db: Session = Depends(get_db)):
    """One generic 401 for unknown email AND wrong password, with equal hashing work for both."""
    _require_secret()
    email_key = (request.email or "").strip().lower()
    check_rate_limit(f"login-email:{email_key}", settings.RATE_LIMIT_AUTH_PER_MINUTE)

    try:
        email = normalize_email(request.email)
    except ValueError:
        email = None
    user = db.query(User).filter(User.email == email).first() if email else None

    if user is None or not user.is_active:
        verify_dummy(request.password)
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_FAILURE,
                            headers={"WWW-Authenticate": "Bearer"})
    if not verify_password(user.password_hash, request.password):
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_FAILURE,
                            headers={"WWW-Authenticate": "Bearer"})

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(request.password)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return _token_response(user)


def _caller(request: Request, db: Session) -> User:
    """The active user behind the request's token (with auth off, the token is checked here)."""
    user: Optional[AuthUser] = current_user(request)
    user_id = user.id if user else None
    version = None
    if user_id is None:  # auth off: the access layer didn't run, so check the token here
        token = bearer_token(request)
        if token is None or not settings.JWT_SECRET:
            raise HTTPException(status_code=401, detail="Not authenticated",
                                headers={"WWW-Authenticate": "Bearer"})
        try:
            claims = decode_access_token(token)
        except TokenError:
            raise HTTPException(status_code=401, detail="Invalid or expired token",
                                headers={"WWW-Authenticate": "Bearer"})
        user_id, version = int(claims["sub"]), claims["ver"]

    record = db.get(User, user_id)
    if record is None or not record.is_active or (version is not None and record.token_version != version):
        raise HTTPException(status_code=401, detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    return record


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    record = _caller(request, db)
    memberships = (
        db.query(WorkspaceMember.workspace_id, WorkspaceMember.role)
        .filter(WorkspaceMember.user_id == record.id)
        .order_by(WorkspaceMember.workspace_id)
        .all()
    )
    return {**_user_dict(record),
            "workspaces": [{"workspace_id": w, "role": r} for w, r in memberships]}


@router.post("/logout-all")
def logout_everywhere(request: Request, db: Session = Depends(get_db)):
    """Revokes every token issued so far for the caller (all browsers and devices)."""
    record = _caller(request, db)
    db.query(User).filter(User.id == record.id).update(
        {User.token_version: User.token_version + 1}, synchronize_session=False
    )
    db.commit()
    return {"revoked": True}
