import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.access import enforce_access
from app.core.config import settings
from app.core.http import REQUEST_ID_HEADER, assert_secure_configuration, install_http_hardening
from app.core.logging import setup_logging
from app.api import (
    agent,
    auth,
    conversations,
    documents,
    evaluation,
    experiments,
    graph,
    health,
    jobs,
    query,
    workspaces,
)

setup_logging()
logger = logging.getLogger(__name__)

_docs_enabled = not settings.is_production


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: refuse to run with uncovered routes or (in production / auth mode) unsafe config
    assert_secure_configuration(app)
    logger.info(
        "KnowledgeFlow AI backend starting up | environment=%s | auth_required=%s | ingest_async=%s",
        settings.ENVIRONMENT, settings.AUTH_REQUIRED, settings.INGEST_ASYNC,
    )
    if settings.RUN_EMBEDDED_WORKER:
        from app.jobs.worker import start_embedded_worker
        start_embedded_worker()
    elif settings.INGEST_ASYNC:
        logger.info("Uploads are queued: run `python -m app.worker` to process them")
    try:
        yield
    finally:  # shutdown: let the embedded worker finish its current job
        if settings.RUN_EMBEDDED_WORKER:
            from app.jobs.worker import stop_embedded_worker
            stop_embedded_worker()


app = FastAPI(
    lifespan=lifespan,
    title="KnowledgeFlow AI",
    version="1.0.0",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

install_http_hardening(app)

# Added last = outermost, so even early 413/429 responses carry CORS headers.
# Tokens travel in the Authorization header, not cookies, so credentials stay off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
    expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
)

# EVERY router goes through the access layer; uncovered routes stop startup.
_guard = [Depends(enforce_access)]
for module in (health, auth, workspaces, documents, jobs, query, conversations,
               graph, agent, evaluation, experiments):
    app.include_router(module.router, dependencies=_guard)
