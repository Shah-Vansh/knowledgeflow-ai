"""
Access control: ONE policy table, enforced by ONE dependency on every router.

Every API route is listed in POLICIES under (METHOD, route template). The
router-level dependency `enforce_access` looks the route up and:

  * public          -> anyone (rate-limited by client IP)
  * authenticated   -> any valid, active user
  * workspace       -> a member of the workspace the request touches, with at
                       least the given role. The workspace id comes from the
                       path / query / JSON body / form, or from a resource
                       (document, conversation, eval set, ...) resolved to the
                       workspace it belongs to.

Deny by default: a route with no policy gets 403 when auth is on, and
`uncovered_routes(app)` lists such routes so a test fails and startup refuses
to start. A non-member gets exactly the same 404 as a missing resource, so ids
can't be probed. With AUTH_REQUIRED=false the dependency does nothing.
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from app.core import ratelimit
from app.core.config import settings
from app.core.security import TokenError, decode_access_token

ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}
ROLES = tuple(ROLE_RANK)
NOT_FOUND = "Not found"


@dataclass(frozen=True)
class AuthUser:
    id: int
    email: str


@dataclass(frozen=True)
class Policy:
    kind: str                         # "public" | "authenticated" | "workspace"
    role: Optional[str] = None        # minimum role for kind="workspace"
    source: Optional[str] = None      # "path" | "query" | "body" | "form"
    param: str = "workspace_id"       # name of the field holding the id
    resource: str = "workspace"       # what the id identifies (resolved to its workspace)
    default: Optional[int] = None     # used when the field is absent; None = required
    rate: str = "default"             # "auth" | "llm" | "default"


def public(rate: str = "default") -> Policy:
    return Policy(kind="public", rate=rate)


def authenticated(rate: str = "default") -> Policy:
    return Policy(kind="authenticated", rate=rate)


def ws(role: str, source: str, param: str = "workspace_id", resource: str = "workspace",
       default: Optional[int] = None, rate: str = "default") -> Policy:
    assert role in ROLE_RANK and source in {"path", "query", "body", "form"}
    return Policy(kind="workspace", role=role, source=source, param=param,
                  resource=resource, default=default, rate=rate)


LLM = "llm"
DEFAULT_WS = 1

POLICIES: Dict[Tuple[str, str], Policy] = {
    # ---- public / account
    ("GET", "/health"): public(),
    ("GET", "/health/live"): public(),
    ("GET", "/health/ready"): public(),
    ("GET", "/metrics"): public(),  # guarded by METRICS_TOKEN in the handler
    ("GET", "/auth/config"): public(),
    ("POST", "/auth/register"): public(rate="auth"),
    ("POST", "/auth/login"): public(rate="auth"),
    ("GET", "/auth/me"): authenticated(),
    ("POST", "/auth/logout-all"): authenticated(rate="auth"),
    # ---- workspaces
    ("GET", "/workspaces"): authenticated(),
    ("POST", "/workspaces"): authenticated(),
    ("DELETE", "/workspaces/{workspace_id}"): ws("owner", "path"),
    ("GET", "/workspaces/{workspace_id}/members"): ws("viewer", "path"),
    ("POST", "/workspaces/{workspace_id}/members"): ws("owner", "path"),
    ("DELETE", "/workspaces/{workspace_id}/members/{user_id}"): ws("owner", "path"),
    # ---- documents
    ("POST", "/documents/upload"): ws("editor", "form", default=DEFAULT_WS),
    ("GET", "/documents"): ws("viewer", "query"),
    ("GET", "/documents/{document_id}/chunks"): ws("viewer", "path", "document_id", "document"),
    ("POST", "/documents/{document_id}/rechunk"): ws("editor", "path", "document_id", "document"),
    ("DELETE", "/documents/{document_id}"): ws("editor", "path", "document_id", "document"),
    # ---- background jobs
    ("GET", "/jobs"): ws("viewer", "query"),
    ("GET", "/jobs/{job_id}"): ws("viewer", "path", "job_id", "job"),
    # ---- query
    ("POST", "/query"): ws("viewer", "body", rate=LLM),
    ("POST", "/query/retrieve"): ws("viewer", "body", rate=LLM),
    # ---- conversations
    ("POST", "/conversations"): ws("viewer", "body", default=DEFAULT_WS),
    ("GET", "/conversations"): ws("viewer", "query"),
    ("GET", "/conversations/{conversation_id}"): ws("viewer", "path", "conversation_id", "conversation"),
    ("DELETE", "/conversations/{conversation_id}"): ws("editor", "path", "conversation_id", "conversation"),
    ("POST", "/conversations/{conversation_id}/messages"): ws(
        "viewer", "path", "conversation_id", "conversation", rate=LLM),
    # ---- graph
    ("POST", "/graph/documents/{document_id}/build"): ws("editor", "path", "document_id", "document", rate=LLM),
    ("GET", "/graph"): ws("viewer", "query", default=DEFAULT_WS),
    ("POST", "/graph/query"): ws("viewer", "body", default=DEFAULT_WS, rate=LLM),
    # ---- agent
    ("POST", "/agent/query"): ws("viewer", "body", default=DEFAULT_WS, rate=LLM),
    # ---- evaluation
    ("POST", "/eval/sets"): ws("editor", "body", default=DEFAULT_WS),
    ("GET", "/eval/sets"): ws("viewer", "query"),
    ("GET", "/eval/sets/{set_id}"): ws("viewer", "path", "set_id", "eval_set"),
    ("DELETE", "/eval/sets/{set_id}"): ws("editor", "path", "set_id", "eval_set"),
    ("POST", "/eval/sets/{set_id}/questions"): ws("editor", "path", "set_id", "eval_set"),
    ("DELETE", "/eval/questions/{question_id}"): ws("editor", "path", "question_id", "eval_question"),
    ("POST", "/eval/sets/{set_id}/generate"): ws("editor", "path", "set_id", "eval_set", rate=LLM),
    ("POST", "/eval/runs"): ws("editor", "body", "eval_set_id", "eval_set", rate=LLM),
    ("GET", "/eval/runs"): ws("viewer", "query", "eval_set_id", "eval_set"),
    ("GET", "/eval/runs/{run_id}"): ws("viewer", "path", "run_id", "eval_run"),
    ("DELETE", "/eval/runs/{run_id}"): ws("editor", "path", "run_id", "eval_run"),
    # ---- experiments
    ("POST", "/experiments"): ws("editor", "body", "eval_set_id", "eval_set"),
    ("GET", "/experiments"): authenticated(),  # the handler filters by membership
    ("GET", "/experiments/{experiment_id}"): ws("viewer", "path", "experiment_id", "experiment"),
    ("DELETE", "/experiments/{experiment_id}"): ws("editor", "path", "experiment_id", "experiment"),
    ("POST", "/experiments/{experiment_id}/run-variant"): ws(
        "editor", "path", "experiment_id", "experiment", rate=LLM),
}


# ------------------------------------------------------------------ helpers
def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=NOT_FOUND)


def rate_limit_for(rate_class: str) -> int:
    return {
        "auth": settings.RATE_LIMIT_AUTH_PER_MINUTE,
        "llm": settings.RATE_LIMIT_LLM_PER_MINUTE,
    }.get(rate_class, settings.RATE_LIMIT_DEFAULT_PER_MINUTE)


def check_rate_limit(key: str, limit: int) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    allowed, retry_after = ratelimit.limiter.hit(key, limit)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests; slow down",
            headers={"Retry-After": str(retry_after)},
        )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def current_user(request: Request) -> Optional[AuthUser]:
    """The authenticated caller, or None when auth is off (enforce_access sets it)."""
    return getattr(request.state, "user", None)


def _as_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


async def _raw_value(request: Request, policy: Policy):
    if policy.source == "path":
        return request.path_params.get(policy.param)
    if policy.source == "query":
        return request.query_params.get(policy.param)
    if policy.source == "body":
        try:
            body = await request.json()
        except Exception:
            return None
        return body.get(policy.param) if isinstance(body, dict) else None
    if policy.source == "form":
        try:
            form = await request.form()
        except Exception:
            return None
        return form.get(policy.param)
    return None


# ---------------------------------------------------------- database work
def _resolve_workspace(db, resource: str, resource_id: int) -> Optional[int]:
    from app.db.models import (Conversation, Document, EvalQuestion, EvalRun, EvalSet,
                               Experiment, Job, Workspace)

    if resource == "workspace":
        return resource_id if db.get(Workspace, resource_id) is not None else None
    if resource == "document":
        row = db.query(Document.workspace_id).filter(
            Document.id == resource_id, Document.deleted_at.is_(None)).first()
    elif resource == "conversation":
        row = db.query(Conversation.workspace_id).filter(Conversation.id == resource_id).first()
    elif resource == "eval_set":
        row = db.query(EvalSet.workspace_id).filter(EvalSet.id == resource_id).first()
    elif resource == "eval_question":
        row = (db.query(EvalSet.workspace_id).join(EvalQuestion, EvalQuestion.eval_set_id == EvalSet.id)
               .filter(EvalQuestion.id == resource_id).first())
    elif resource == "eval_run":
        row = (db.query(EvalSet.workspace_id).join(EvalRun, EvalRun.eval_set_id == EvalSet.id)
               .filter(EvalRun.id == resource_id).first())
    elif resource == "experiment":
        row = (db.query(EvalSet.workspace_id).join(Experiment, Experiment.eval_set_id == EvalSet.id)
               .filter(Experiment.id == resource_id).first())
    elif resource == "job":
        row = db.query(Job.workspace_id).filter(Job.id == resource_id).first()
    else:
        raise ValueError(f"unknown resource kind {resource!r}")
    return row[0] if row else None


def _authorize(user_id: int, policy: Policy, resource_id: Optional[int], token_version: int = 0):
    """Runs in a worker thread with its own short-lived session."""
    from app.db.models import User, WorkspaceMember
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None or not user.is_active or user.token_version != token_version:
            raise _unauthorized("Invalid or expired token")
        auth_user = AuthUser(id=user.id, email=user.email)
        if policy.kind != "workspace":
            return auth_user, None, None

        workspace_id = _resolve_workspace(db, policy.resource, resource_id)
        if workspace_id is None:
            raise _not_found()
        member = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user.id})
        if member is None:
            raise _not_found()  # identical to a missing resource: no id probing
        if ROLE_RANK.get(member.role, 0) < ROLE_RANK[policy.role]:
            raise HTTPException(status_code=403, detail=f"This action needs the {policy.role} role")
        return auth_user, workspace_id, member.role
    finally:
        db.close()


# --------------------------------------------------------------- dependency
async def enforce_access(request: Request) -> None:
    if not settings.AUTH_REQUIRED:
        return

    route = request.scope.get("route")
    template = getattr(route, "path", None)
    policy = POLICIES.get((request.method.upper(), template)) if template else None
    if policy is None:
        raise HTTPException(status_code=403, detail="Forbidden")  # deny by default

    limit = rate_limit_for(policy.rate)
    if policy.kind == "public":
        check_rate_limit(f"{policy.rate}:ip:{client_ip(request)}", limit)
        return

    token = bearer_token(request)
    if token is None:
        raise _unauthorized()
    try:
        claims = decode_access_token(token)
    except TokenError:
        raise _unauthorized("Invalid or expired token")
    user_id = int(claims["sub"])
    check_rate_limit(f"{policy.rate}:user:{user_id}", limit)

    resource_id = None
    if policy.kind == "workspace":
        raw = await _raw_value(request, policy)
        if raw is None:
            raw = policy.default
        if raw is None:
            raise HTTPException(status_code=422, detail=f"{policy.param} is required")
        resource_id = _as_int(raw)
        if resource_id is None:
            raise HTTPException(status_code=422, detail=f"{policy.param} must be an integer")

    user, workspace_id, role = await run_in_threadpool(_authorize, user_id, policy, resource_id, claims["ver"])
    request.state.user = user
    request.state.workspace_id = workspace_id
    request.state.workspace_role = role


# --------------------------------------------------------------- coverage
def _has_enforcement(route: APIRoute) -> bool:
    return any(dep.call is enforce_access for dep in route.dependant.dependencies)


def uncovered_routes(app) -> List[str]:
    """API routes that have no policy entry or are not guarded by enforce_access."""
    problems: List[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods or []):
            if (method, route.path) not in POLICIES:
                problems.append(f"{method} {route.path}: no access policy")
        if not _has_enforcement(route):
            problems.append(f"{route.path}: router not guarded by enforce_access")
    return problems


def stale_policies(app) -> List[Tuple[str, str]]:
    """Policy entries whose route no longer exists (kept tidy by a test)."""
    existing = {
        (method, route.path)
        for route in app.routes if isinstance(route, APIRoute)
        for method in (route.methods or [])
    }
    return sorted(set(POLICIES) - existing)
