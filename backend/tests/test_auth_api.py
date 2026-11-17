"""Registration, login, /auth/me and workspace membership management."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models import User, Workspace, WorkspaceMember
from app.db.session import SessionLocal
from app.main import app
from tests.auth_helpers import PASSWORD, auth_on, bearer, delete_workspaces  # noqa: F401

client = TestClient(app)


@pytest.fixture
def empty_users():
    """These tests need a users table with nobody in it (first-user rules)."""
    db = SessionLocal()
    db.query(User).delete()
    db.commit()
    db.close()
    created_ws = []
    yield created_ws
    db = SessionLocal()
    db.query(User).delete()
    delete_workspaces(db, created_ws)
    db.commit()
    db.close()


def _register(email, password=PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password})


def _login(email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_first_user_claims_every_existing_workspace(empty_users, auth_on):
    db = SessionLocal()
    ws = Workspace(name=f"claim-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    db.commit()
    empty_users.append(ws.id)
    all_ids = {w for (w,) in db.query(Workspace.id).all()}
    db.close()

    response = _register("First.User@Example.com")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == "first.user@example.com"        # stored lowercase
    assert body["claimed_existing_workspaces"] is True
    assert body["token_type"] == "bearer" and body["access_token"]

    me = client.get("/auth/me", headers=bearer(body["access_token"])).json()
    assert {m["workspace_id"] for m in me["workspaces"]} == all_ids
    assert {m["role"] for m in me["workspaces"]} == {"owner"}

    second = _register("second@example.com")
    assert second.status_code == 201
    assert second.json()["claimed_existing_workspaces"] is False
    me2 = client.get("/auth/me", headers=bearer(second.json()["access_token"])).json()
    assert me2["workspaces"] == []


def test_closed_registration_still_lets_the_first_user_in(empty_users, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", False)
    assert client.get("/auth/config").json()["registration_open"] is True   # nobody yet
    assert _register("only@example.com").status_code == 201
    assert client.get("/auth/config").json()["registration_open"] is False
    response = _register("late@example.com")
    assert response.status_code == 403


def test_duplicate_email_is_409_case_insensitive(empty_users):
    assert _register("dup@example.com").status_code == 201
    assert _register("DUP@example.com").status_code == 409


@pytest.mark.parametrize("password", ["short", "aaaaaaaaaaaaaa", "password123", "weak@example.com"])
def test_weak_passwords_are_422(empty_users, password):
    response = _register("weak@example.com", password)
    assert response.status_code == 422


def test_invalid_email_is_422(empty_users):
    assert _register("not-an-email").status_code == 422


def test_register_without_jwt_secret_is_503(empty_users, monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET", "")
    assert _register("x@example.com").status_code == 503


def test_login_success_sets_last_login(empty_users):
    _register("login@example.com")
    response = _login("LOGIN@example.com")
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["last_login_at"] is not None
    me = client.get("/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200 and me.json()["email"] == "login@example.com"


def test_login_failures_are_generic(empty_users):
    _register("known@example.com")
    wrong_password = _login("known@example.com", "not-the-password-123")
    unknown_email = _login("unknown@example.com")
    malformed = _login("no-at-sign")
    for response in (wrong_password, unknown_email, malformed):
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid email or password"}


def test_inactive_user_cannot_log_in(empty_users):
    _register("inactive@example.com")
    db = SessionLocal()
    db.query(User).filter(User.email == "inactive@example.com").update({"is_active": False})
    db.commit()
    db.close()
    assert _login("inactive@example.com").status_code == 401


def test_login_is_rate_limited_per_email(empty_users, monkeypatch):
    # auth OFF here, so only the per-email limit in the handler applies (not the per-IP one)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 3)
    _register("target@example.com")
    for _ in range(3):
        assert _login("target@example.com", "wrong-password-xyz").status_code == 401
    blocked = _login("target@example.com")          # even the right password is held back
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert _login("someone-else@example.com").status_code == 401   # other emails unaffected


def test_auth_endpoints_rate_limited_per_ip_when_auth_on(empty_users, auth_on, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 2)
    _register("ip1@example.com")
    _register("ip2@example.com")
    response = _login("ip1@example.com")
    assert response.status_code == 429 and "retry-after" in response.headers


def test_me_without_token_is_401(empty_users):
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


# ------------------------------------------------------------------ members
def test_members_and_last_owner_rule(empty_users, auth_on):
    owner = _register("owner@example.com").json()
    member = _register("member@example.com").json()
    h_owner, h_member = bearer(owner["access_token"]), bearer(member["access_token"])

    created = client.post("/workspaces", json={"name": f"team-{uuid.uuid4().hex[:8]}"}, headers=h_owner)
    assert created.status_code == 201 and created.json()["role"] == "owner"
    ws_id = created.json()["id"]
    empty_users.append(ws_id)

    # the new user can't see it yet
    assert ws_id not in [w["id"] for w in client.get("/workspaces", headers=h_member).json()]
    assert client.get(f"/workspaces/{ws_id}/members", headers=h_member).status_code == 404

    added = client.post(f"/workspaces/{ws_id}/members",
                        json={"email": "MEMBER@example.com", "role": "editor"}, headers=h_owner)
    assert added.status_code == 201 and added.json()["role"] == "editor"
    listed = client.get(f"/workspaces/{ws_id}/members", headers=h_member).json()
    assert {(m["email"], m["role"]) for m in listed} == {("owner@example.com", "owner"),
                                                         ("member@example.com", "editor")}

    # an editor can't manage members
    assert client.post(f"/workspaces/{ws_id}/members", json={"email": "owner@example.com", "role": "viewer"},
                       headers=h_member).status_code == 403

    bad_role = client.post(f"/workspaces/{ws_id}/members", json={"email": "member@example.com", "role": "admin"},
                           headers=h_owner)
    assert bad_role.status_code == 422
    unknown = client.post(f"/workspaces/{ws_id}/members", json={"email": "ghost@example.com"}, headers=h_owner)
    assert unknown.status_code == 404

    # the only owner can neither leave nor demote themself
    owner_id = owner["user"]["id"]
    assert client.delete(f"/workspaces/{ws_id}/members/{owner_id}", headers=h_owner).status_code == 409
    demote = client.post(f"/workspaces/{ws_id}/members", json={"email": "owner@example.com", "role": "viewer"},
                         headers=h_owner)
    assert demote.status_code == 409
    assert demote.json()["detail"] == "A workspace needs at least one owner"

    # with a second owner, the first may leave
    client.post(f"/workspaces/{ws_id}/members", json={"email": "member@example.com", "role": "owner"},
                headers=h_owner)
    assert client.delete(f"/workspaces/{ws_id}/members/{owner_id}", headers=h_owner).status_code == 200
    assert client.get(f"/workspaces/{ws_id}/members", headers=h_owner).status_code == 404


def test_deleting_a_workspace_removes_its_memberships(empty_users, auth_on):
    owner = _register("del@example.com").json()
    h = bearer(owner["access_token"])
    ws_id = client.post("/workspaces", json={"name": f"gone-{uuid.uuid4().hex[:8]}"}, headers=h).json()["id"]
    assert client.delete(f"/workspaces/{ws_id}", headers=h).status_code == 200
    db = SessionLocal()
    assert db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == ws_id).count() == 0
    db.close()
