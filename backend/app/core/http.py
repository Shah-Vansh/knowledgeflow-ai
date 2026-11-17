"""HTTP hardening: security headers, request ids, early 413, and the startup configuration check."""
import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core import metrics
from app.core.config import settings
from app.core.logging import request_id_var

logger = logging.getLogger(__name__)
access_logger = logging.getLogger("kf.access")
_QUIET_ROUTES = {"/health", "/health/live", "/health/ready", "/metrics"}

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_DOCS_PREFIXES = ("/docs", "/redoc")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'"


class InsecureConfigurationError(RuntimeError):
    pass


def request_id_from(value) -> str:
    """Echo a well-formed incoming id (for tracing across services), otherwise make one."""
    if value and _SAFE_REQUEST_ID.match(value):
        return value
    return uuid.uuid4().hex


def max_request_bytes() -> int:
    return (settings.MAX_UPLOAD_MB + 1) * 1024 * 1024


def route_label(request: Request) -> str:
    """The route TEMPLATE (/documents/{document_id}), never the raw path: bounded label values."""
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


def _record(request: Request, status: int, seconds: float) -> None:
    route = route_label(request)
    metrics.HTTP_REQUESTS.inc(method=request.method, route=route, status=status)
    metrics.HTTP_SECONDS.observe(seconds, method=request.method, route=route)
    user = getattr(request.state, "user", None)
    level = logging.DEBUG if route in _QUIET_ROUTES and status < 400 else logging.INFO
    access_logger.log(
        level, "%s %s -> %s in %.0f ms", request.method, route, status, seconds * 1000,
        extra={"method": request.method, "route": route, "status": status,
               "duration_ms": round(seconds * 1000, 1), "user_id": user.id if user else None},
    )


def install_http_hardening(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        request_id = request_id_from(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > max_request_bytes():
                # Rejected before the body is read. Chunked uploads have no length; the
                # upload handler still enforces MAX_UPLOAD_MB while streaming them.
                response = JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body is too large (limit {settings.MAX_UPLOAD_MB} MB)"},
                )
            else:
                response = await call_next(request)
            status = response.status_code

            for name, value in SECURITY_HEADERS.items():
                response.headers.setdefault(name, value)
            if not request.url.path.startswith(_DOCS_PREFIXES):
                response.headers.setdefault("Content-Security-Policy", API_CSP)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            _record(request, status, time.perf_counter() - started)
            request_id_var.reset(token)


def assert_secure_configuration(app: FastAPI) -> None:
    """
    Refuses to start when any route lacks an access policy (always), or when the
    configuration is unsafe in production / auth mode. In plain local development
    the configuration problems are only logged as warnings.
    """
    from app.core.access import uncovered_routes
    from app.core.security import security_problems

    uncovered = uncovered_routes(app)
    if uncovered:
        raise InsecureConfigurationError("Routes without an access policy: " + "; ".join(uncovered))

    problems = security_problems(settings)
    if not problems:
        return
    if settings.is_production or settings.AUTH_REQUIRED:
        raise InsecureConfigurationError("Insecure configuration: " + "; ".join(problems))
    for problem in problems:
        logger.warning("Security (development mode, not enforced): %s", problem)
