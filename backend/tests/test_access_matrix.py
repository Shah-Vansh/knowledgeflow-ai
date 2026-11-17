"""
The access-control contract, checked on the REAL app:

  (a) every API route has a policy and is guarded by enforce_access;
  (b) a matrix over every route x {anon, non-member, member of another workspace,
      viewer, owner} expects 401 / 404 "Not found" / 403 / allowed;
  (c) list endpoints never leak other workspaces;
  (d) a nonexistent id gives the same 404 as a forbidden one.
"""
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.access import NOT_FOUND, POLICIES, enforce_access, stale_policies, uncovered_routes
from app.main import app
from tests.auth_helpers import PASSWORD, auth_on, no_llm, world  # noqa: F401  (fixtures)

client = TestClient(app, raise_server_exceptions=False)

ACTORS = ("anon", "nonmember", "other", "viewer", "owner")  # owner last: it may delete things
NOT_FOUND_BODY = {"detail": NOT_FOUND}


def _requests(w):
    """(METHOD, template) -> function(actor) -> (method, url, request kwargs). One per policy."""
    A, r = w.ws["A"], w.res["A"]
    doc, conv, eset = r["document"], r["conversation"], r["eval_set"]
    q, run, exp = r["eval_question"], r["eval_run"], r["experiment"]
    owner_email = w.users["owner"]["email"]
    return {
        ("GET", "/health"): lambda a: ("GET", "/health", {}),
        ("GET", "/health/live"): lambda a: ("GET", "/health/live", {}),
        ("GET", "/health/ready"): lambda a: ("GET", "/health/ready", {}),
        ("GET", "/metrics"): lambda a: ("GET", "/metrics", {}),
        ("GET", "/jobs"): lambda a: ("GET", f"/jobs?workspace_id={A}", {}),
        ("GET", "/jobs/{job_id}"): lambda a: ("GET", f"/jobs/{r['job']}", {}),
        ("GET", "/auth/config"): lambda a: ("GET", "/auth/config", {}),
        ("POST", "/auth/register"): lambda a: ("POST", "/auth/register", {"json": {
            "email": f"new-{a}@{w.prefix}.example.com", "password": PASSWORD}}),
        ("POST", "/auth/login"): lambda a: ("POST", "/auth/login", {"json": {
            "email": owner_email, "password": PASSWORD}}),
        ("GET", "/auth/me"): lambda a: ("GET", "/auth/me", {}),
        ("POST", "/auth/logout-all"): lambda a: ("POST", "/auth/logout-all", {}),
        ("GET", "/workspaces"): lambda a: ("GET", "/workspaces", {}),
        ("POST", "/workspaces"): lambda a: ("POST", "/workspaces", {"json": {"name": f"{w.prefix}-new-{a}"}}),
        ("DELETE", "/workspaces/{workspace_id}"): lambda a: ("DELETE", f"/workspaces/{A}", {}),
        ("GET", "/workspaces/{workspace_id}/members"): lambda a: ("GET", f"/workspaces/{A}/members", {}),
        ("POST", "/workspaces/{workspace_id}/members"): lambda a: ("POST", f"/workspaces/{A}/members", {
            "json": {"email": w.users["spare"]["email"], "role": "viewer"}}),
        ("DELETE", "/workspaces/{workspace_id}/members/{user_id}"): lambda a: (
            "DELETE", f"/workspaces/{A}/members/{w.users['viewer']['id']}", {}),
        ("POST", "/documents/upload"): lambda a: ("POST", "/documents/upload", {
            "files": {"file": ("acl.txt", b"Access control test document text.", "text/plain")},
            "data": {"workspace_id": str(A)}}),
        ("GET", "/documents"): lambda a: ("GET", f"/documents?workspace_id={A}", {}),
        ("GET", "/documents/{document_id}/chunks"): lambda a: ("GET", f"/documents/{doc}/chunks", {}),
        ("POST", "/documents/{document_id}/rechunk"): lambda a: ("POST", f"/documents/{doc}/rechunk", {
            "json": {"strategy": "fixed_size", "chunk_size": 200, "overlap": 0}}),
        ("DELETE", "/documents/{document_id}"): lambda a: ("DELETE", f"/documents/{doc}", {}),
        ("POST", "/query"): lambda a: ("POST", "/query", {"json": {"question": "anything?", "workspace_id": A}}),
        ("POST", "/query/retrieve"): lambda a: ("POST", "/query/retrieve", {"json": {
            "question": "anything?", "workspace_id": A, "mode": "sparse"}}),
        ("POST", "/conversations"): lambda a: ("POST", "/conversations", {"json": {"workspace_id": A}}),
        ("GET", "/conversations"): lambda a: ("GET", f"/conversations?workspace_id={A}", {}),
        ("GET", "/conversations/{conversation_id}"): lambda a: ("GET", f"/conversations/{conv}", {}),
        ("DELETE", "/conversations/{conversation_id}"): lambda a: ("DELETE", f"/conversations/{conv}", {}),
        ("POST", "/conversations/{conversation_id}/messages"): lambda a: (
            "POST", f"/conversations/{conv}/messages", {"json": {"content": "hello?"}}),
        ("POST", "/graph/documents/{document_id}/build"): lambda a: (
            "POST", f"/graph/documents/{doc}/build", {"json": {}}),
        ("GET", "/graph"): lambda a: ("GET", f"/graph?workspace_id={A}", {}),
        ("POST", "/graph/query"): lambda a: ("POST", "/graph/query", {"json": {"question": "who?", "workspace_id": A}}),
        ("POST", "/agent/query"): lambda a: ("POST", "/agent/query", {"json": {"question": "who?", "workspace_id": A}}),
        ("POST", "/eval/sets"): lambda a: ("POST", "/eval/sets", {"json": {"workspace_id": A, "name": "acl set"}}),
        ("GET", "/eval/sets"): lambda a: ("GET", f"/eval/sets?workspace_id={A}", {}),
        ("GET", "/eval/sets/{set_id}"): lambda a: ("GET", f"/eval/sets/{eset}", {}),
        ("DELETE", "/eval/sets/{set_id}"): lambda a: ("DELETE", f"/eval/sets/{eset}", {}),
        ("POST", "/eval/sets/{set_id}/questions"): lambda a: ("POST", f"/eval/sets/{eset}/questions", {
            "json": {"question": "Is this another question?", "evidence": ["text"]}}),
        ("DELETE", "/eval/questions/{question_id}"): lambda a: ("DELETE", f"/eval/questions/{q}", {}),
        ("POST", "/eval/sets/{set_id}/generate"): lambda a: ("POST", f"/eval/sets/{eset}/generate", {
            "json": {"count": 1}}),
        ("POST", "/eval/runs"): lambda a: ("POST", "/eval/runs", {"json": {
            "eval_set_id": eset, "config": {"mode": "sparse"}}}),
        ("GET", "/eval/runs"): lambda a: ("GET", f"/eval/runs?eval_set_id={eset}", {}),
        ("GET", "/eval/runs/{run_id}"): lambda a: ("GET", f"/eval/runs/{run}", {}),
        ("DELETE", "/eval/runs/{run_id}"): lambda a: ("DELETE", f"/eval/runs/{run}", {}),
        ("POST", "/experiments"): lambda a: ("POST", "/experiments", {"json": {
            "eval_set_id": eset, "name": "acl exp", "variants": [{"label": "x"}]}}),
        ("GET", "/experiments"): lambda a: ("GET", "/experiments", {}),
        ("GET", "/experiments/{experiment_id}"): lambda a: ("GET", f"/experiments/{exp}", {}),
        ("DELETE", "/experiments/{experiment_id}"): lambda a: ("DELETE", f"/experiments/{exp}", {}),
        ("POST", "/experiments/{experiment_id}/run-variant"): lambda a: (
            "POST", f"/experiments/{exp}/run-variant", {"json": {"index": 0}}),
    }


def _expected(policy, actor):
    if policy.kind == "public":
        return "allowed"
    if actor == "anon":
        return 401
    if policy.kind == "authenticated":
        return "allowed"
    if actor in ("nonmember", "other"):
        return 404
    if actor == "viewer":
        return "allowed" if policy.role == "viewer" else 403
    return "allowed"


def _call(w, key, actor):
    method, url, kwargs = _requests(w)[key](actor)
    return client.request(method, url, headers=w.headers(actor), **kwargs)


# ------------------------------------------------------------------ (a) coverage
def test_every_route_has_a_policy_and_the_guard():
    assert uncovered_routes(app) == []


def test_no_stale_policies():
    assert stale_policies(app) == []


def test_matrix_covers_every_policy(world):
    assert set(_requests(world)) == set(POLICIES)


def test_unlisted_route_is_denied_and_reported(auth_on):
    router = APIRouter()

    @router.get("/secret-new-feature")
    def secret():
        return {"leaked": True}

    unguarded = APIRouter()

    @unguarded.get("/health")
    def health_copy():
        return {}

    toy = FastAPI()
    toy.include_router(router, dependencies=[Depends(enforce_access)])
    toy.include_router(unguarded)
    problems = uncovered_routes(toy)
    assert any("/secret-new-feature" in p and "no access policy" in p for p in problems)
    assert any("/health" in p and "not guarded" in p for p in problems)
    response = TestClient(toy).get("/secret-new-feature")
    assert response.status_code == 403 and "leaked" not in response.text


# ------------------------------------------------------------------ (b) matrix
@pytest.mark.parametrize("key", sorted(POLICIES), ids=lambda k: f"{k[0]} {k[1]}")
def test_access_matrix(key, world, auth_on, no_llm):
    policy = POLICIES[key]
    for actor in ACTORS:
        response = _call(world, key, actor)
        expected = _expected(policy, actor)
        where = f"{key[0]} {key[1]} as {actor}: {response.status_code} {response.text[:200]}"
        if expected == 401:
            assert response.status_code == 401, where
            assert response.headers.get("www-authenticate") == "Bearer", where
        elif expected == 404:
            assert response.status_code == 404 and response.json() == NOT_FOUND_BODY, where
        elif expected == 403:
            assert response.status_code == 403, where
        else:
            assert response.status_code not in (401, 403, 429, 500), where
            if response.status_code == 404:
                assert response.json() != NOT_FOUND_BODY, where


def test_invalid_and_tampered_tokens_get_401(world, auth_on):
    token = world.users["owner"]["token"]
    head, payload, signature = token.split(".")
    for bad in ("garbage", f"{head}.{payload}.{signature[:-2]}xx", ""):
        response = client.get("/workspaces", headers={"Authorization": f"Bearer {bad}"})
        assert response.status_code == 401
    assert client.get("/workspaces", headers={"Authorization": f"Basic {token}"}).status_code == 401


def test_token_of_deleted_user_gets_401(world, auth_on):
    from app.db.models import User
    from app.db.session import SessionLocal

    db = SessionLocal()
    db.query(User).filter(User.id == world.users["spare"]["id"]).delete()
    db.commit()
    db.close()
    assert client.get("/workspaces", headers=world.headers("spare")).status_code == 401


def test_missing_workspace_id_is_required_when_auth_on(world, auth_on, no_llm):
    h = world.headers("owner")
    assert client.get("/documents", headers=h).status_code == 422
    assert client.get("/conversations", headers=h).status_code == 422
    assert client.get("/eval/sets", headers=h).status_code == 422
    assert client.get("/eval/runs", headers=h).status_code == 422
    assert client.post("/query", json={"question": "x?"}, headers=h).status_code == 422
    assert client.post("/query/retrieve", json={"question": "x?"}, headers=h).status_code == 422


# ------------------------------------------------------------------ (c) no leaks
def test_list_endpoints_never_leak_other_workspaces(world, auth_on):
    h = world.headers("other")
    B, rb = world.ws["B"], world.res["B"]

    workspaces = client.get("/workspaces", headers=h).json()
    assert [ws["id"] for ws in workspaces] == [B]
    assert workspaces[0]["role"] == "owner"

    docs = client.get(f"/documents?workspace_id={B}", headers=h).json()
    assert [d["id"] for d in docs] == [rb["document"]]
    convs = client.get(f"/conversations?workspace_id={B}", headers=h).json()
    assert [c["id"] for c in convs] == [rb["conversation"]]
    sets = client.get(f"/eval/sets?workspace_id={B}", headers=h).json()
    assert [s["id"] for s in sets] == [rb["eval_set"]]
    runs = client.get(f"/eval/runs?eval_set_id={rb['eval_set']}", headers=h).json()
    assert [r["id"] for r in runs] == [rb["eval_run"]]
    experiments = client.get("/experiments", headers=h).json()
    assert [e["id"] for e in experiments] == [rb["experiment"]]
    jobs = client.get(f"/jobs?workspace_id={B}", headers=h).json()
    assert [j["id"] for j in jobs] == [rb["job"]]

    # asking for A's lists directly is the same 404 as anything else forbidden
    A, ra = world.ws["A"], world.res["A"]
    for url in (f"/documents?workspace_id={A}", f"/conversations?workspace_id={A}",
                f"/eval/sets?workspace_id={A}", f"/eval/runs?eval_set_id={ra['eval_set']}",
                f"/graph?workspace_id={A}", f"/jobs?workspace_id={A}"):
        response = client.get(url, headers=h)
        assert response.status_code == 404 and response.json() == NOT_FOUND_BODY, url

    # a user with no workspaces sees nothing at all
    h0 = world.headers("nonmember")
    assert client.get("/workspaces", headers=h0).json() == []
    assert client.get("/experiments", headers=h0).json() == []


# ------------------------------------------------------------------ (d) no probing
def test_nonexistent_id_looks_exactly_like_a_forbidden_one(world, auth_on):
    missing = 2_000_000_000
    ra = world.res["A"]
    pairs = [
        ("/documents/{}/chunks", ra["document"]),
        ("/conversations/{}", ra["conversation"]),
        ("/eval/sets/{}", ra["eval_set"]),
        ("/eval/runs/{}", ra["eval_run"]),
        ("/experiments/{}", ra["experiment"]),
        ("/jobs/{}", ra["job"]),
        ("/workspaces/{}/members", world.ws["A"]),
    ]
    for template, real_id in pairs:
        as_owner_missing = client.get(template.format(missing), headers=world.headers("owner"))
        as_stranger_real = client.get(template.format(real_id), headers=world.headers("other"))
        assert as_owner_missing.status_code == as_stranger_real.status_code == 404, template
        assert as_owner_missing.json() == as_stranger_real.json() == NOT_FOUND_BODY, template


def test_auth_off_keeps_the_open_single_user_behaviour(world):
    # AUTH_REQUIRED=false (test default): no token needed, "all workspaces" still allowed
    assert client.get("/documents").status_code == 200
    assert client.get(f"/workspaces/{world.ws['A']}/members").status_code == 200
