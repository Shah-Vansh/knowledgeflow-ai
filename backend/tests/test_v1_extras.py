"""
v1.0 additions: duplicate-upload detection, "log out everywhere" token revocation,
the locked last-owner check and the lifespan startup hook.
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.api.workspaces import _owner_count
from app.core.config import settings
from app.core.security import TokenError, create_access_token, decode_access_token
from app.db.models import Document, Job, Workspace
from app.db.session import SessionLocal
from app.main import app
from tests.auth_helpers import PASSWORD, auth_on, delete_workspaces, world  # noqa: F401  (fixtures)

client = TestClient(app)
BODY = b"Duplicate detection test. The Porto warehouse stores 1200 pallets of spare parts."


@pytest.fixture
def ws():
    db = SessionLocal()
    ids = []
    for _ in range(2):
        workspace = Workspace(name=f"dup-{uuid.uuid4().hex[:8]}")
        db.add(workspace)
        db.flush()
        ids.append(workspace.id)
    db.commit()
    db.close()
    yield ids
    db = SessionLocal()
    db.query(Job).filter(Job.workspace_id.in_(ids)).delete(synchronize_session=False)
    delete_workspaces(db, ids)
    db.commit()
    db.close()


def _upload(workspace_id, content=BODY, name="dup.txt", **extra):
    data = {"workspace_id": str(workspace_id), **{k: str(v).lower() for k, v in extra.items()}}
    return client.post("/documents/upload", files={"file": (name, content, "text/plain")}, data=data)


def _token(claims: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {"iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=5)).timestamp()), **claims}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


# ------------------------------------------------------------------ duplicates
def test_same_file_twice_in_one_workspace_is_rejected(ws):
    first = _upload(ws[0])
    assert first.status_code == 200
    doc_id = first.json()["document_id"]
    second = _upload(ws[0], name="renamed-copy.txt")      # same bytes, different name
    assert second.status_code == 409
    assert f"#{doc_id}" in second.json()["detail"] and "dup.txt" in second.json()["detail"]
    db = SessionLocal()
    assert db.query(Document).filter(Document.workspace_id == ws[0]).count() == 1
    assert len(db.get(Document, doc_id).content_sha256) == 64
    db.close()


def test_duplicate_allowed_when_asked_or_in_another_workspace(ws):
    assert _upload(ws[0]).status_code == 200
    assert _upload(ws[0], allow_duplicate=True).status_code == 200
    assert _upload(ws[1]).status_code == 200
    assert _upload(ws[0], content=BODY + b" A different file.").status_code == 200


def test_deleted_or_failed_documents_do_not_block_a_reupload(ws):
    doc_id = _upload(ws[0]).json()["document_id"]
    assert client.delete(f"/documents/{doc_id}").status_code == 200
    assert _upload(ws[0]).status_code == 200

    blank = b"   \n\n  "
    assert _upload(ws[1], content=blank, name="blank.txt").status_code == 422   # fails to process
    assert _upload(ws[1], content=blank, name="blank.txt").status_code == 422   # not a 409


def test_queued_upload_also_counts_as_a_duplicate(ws, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_ASYNC", True)
    assert _upload(ws[0]).status_code == 202
    assert _upload(ws[0]).status_code == 409


# ------------------------------------------------------------------ token revocation
def test_logout_everywhere_revokes_existing_tokens(world, auth_on):
    old = world.headers("owner")
    assert client.get("/workspaces", headers=old).status_code == 200
    assert client.post("/auth/logout-all", headers=old).json() == {"revoked": True}
    assert client.get("/workspaces", headers=old).status_code == 401
    assert client.get("/auth/me", headers=old).status_code == 401

    fresh = client.post("/auth/login", json={"email": world.users["owner"]["email"], "password": PASSWORD})
    assert fresh.status_code == 200
    token = fresh.json()["access_token"]
    assert decode_access_token(token)["ver"] == 1
    assert client.get("/workspaces", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/workspaces", headers=world.headers("viewer")).status_code == 200  # others unaffected


def test_logout_everywhere_works_with_auth_off_too(world):
    headers = world.headers("viewer")
    assert client.post("/auth/logout-all", headers=headers).status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401
    assert client.post("/auth/logout-all").status_code == 401


def test_token_without_version_counts_as_version_zero():
    assert decode_access_token(_token({"sub": "5"}))["ver"] == 0
    assert decode_access_token(create_access_token(5, "a@b.com", version=3))["ver"] == 3


@pytest.mark.parametrize("bad", ["1", -1, True, 1.5])
def test_malformed_token_version_is_rejected(bad):
    with pytest.raises(TokenError):
        decode_access_token(_token({"sub": "5", "ver": bad}))


# ------------------------------------------------------------------ last-owner lock
def test_owner_count_locks_owner_rows_until_commit(world):
    workspace_id = world.ws["A"]
    first = SessionLocal()
    second = SessionLocal()
    try:
        assert _owner_count(first, workspace_id) == 1          # holds the row lock (no commit yet)
        second.execute(text("SET lock_timeout = '1s'"))
        with pytest.raises(OperationalError):
            _owner_count(second, workspace_id)                 # a concurrent demotion has to wait
        second.rollback()
        first.commit()                                          # lock released
        assert _owner_count(second, workspace_id) == 1
        second.commit()
    finally:
        first.close()
        second.close()


def test_last_owner_still_cannot_be_removed(world, auth_on):
    A, owner = world.ws["A"], world.users["owner"]
    response = client.delete(f"/workspaces/{A}/members/{owner['id']}", headers=world.headers("owner"))
    assert response.status_code == 409


# ------------------------------------------------------------------ lifespan
def test_lifespan_startup_and_shutdown_run():
    with TestClient(app) as running:
        assert running.get("/health/live").status_code == 200


def test_lifespan_refuses_insecure_production_config(monkeypatch):
    from app.core.http import InsecureConfigurationError

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(InsecureConfigurationError):
        with TestClient(app):
            pass
