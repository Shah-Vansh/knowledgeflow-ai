"""
Health, readiness and metrics.

  GET /health        the original check (database reachable), kept for compatibility
  GET /health/live   liveness: the process answers. Never touches the database, so a
                     slow database doesn't get the process restarted.
  GET /health/ready  readiness: the database answers AND its schema is at the
                     migration head this code expects. 503 otherwise, so a load
                     balancer keeps traffic away until `alembic upgrade head` ran.
  GET /metrics       Prometheus text format. Needs `Authorization: Bearer <METRICS_TOKEN>`
                     when METRICS_TOKEN is set; with auth on and no token it is disabled (404).
"""
import hmac
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.core import metrics
from app.core.access import bearer_token
from app.core.config import settings
from app.db.session import SessionLocal, check_db_connection

router = APIRouter()
logger = logging.getLogger(__name__)

ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"


@router.get("/health")
def health_check():
    db_connected = check_db_connection()

    payload = {
        "status": "ok" if db_connected else "error",
        "db_connected": db_connected,
        "environment": settings.ENVIRONMENT,
    }

    if not db_connected:
        payload["error"] = "Database connection failed"
        return JSONResponse(status_code=503, content=payload)

    return payload


@router.get("/health/live")
def liveness():
    return {"status": "alive"}


@lru_cache(maxsize=1)
def expected_migration_head() -> Optional[str]:
    """The newest revision in alembic/versions (what this code was written against)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    heads = ScriptDirectory.from_config(config).get_heads()
    return heads[0] if len(heads) == 1 else None


def current_migration() -> Optional[str]:
    db = SessionLocal()
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        db.close()


@router.get("/health/ready")
def readiness():
    checks = {"database": check_db_connection(), "migrations": False}
    if checks["database"]:
        try:
            checks["migrations"] = current_migration() == expected_migration_head()
        except Exception as exc:
            logger.error("Readiness: could not read the migration version: %s", type(exc).__name__)
    ready = all(checks.values())
    body = {"status": "ready" if ready else "not_ready", "checks": checks}
    return JSONResponse(status_code=200 if ready else 503, content=body)


def _authorize_metrics(request: Request) -> None:
    if settings.METRICS_TOKEN:
        supplied = bearer_token(request) or ""
        if not hmac.compare_digest(supplied.encode(), settings.METRICS_TOKEN.encode()):
            raise HTTPException(status_code=401, detail="Not authenticated",
                                headers={"WWW-Authenticate": "Bearer"})
    elif settings.AUTH_REQUIRED:
        raise HTTPException(status_code=404, detail="Metrics are disabled; set METRICS_TOKEN to enable them")


@router.get("/metrics")
def metrics_endpoint(request: Request):
    _authorize_metrics(request)
    from app.jobs.queue import queue_stats
    from app.rag.embeddings import query_cache

    lines = metrics.render_process_metrics()
    lines += metrics.gauge_lines("kf_embedding_cache_entries", "Query embeddings held in memory",
                                 [({}, len(query_cache))])
    lines += metrics.gauge_lines("kf_embedding_cache_hits", "Query embedding cache hits since start",
                                 [({}, query_cache.hits)])
    lines += metrics.gauge_lines("kf_embedding_cache_misses", "Query embedding cache misses since start",
                                 [({}, query_cache.misses)])
    db = SessionLocal()
    try:
        stats = queue_stats(db)
        lines += metrics.gauge_lines("kf_jobs", "Jobs in the queue table by status",
                                     [({"status": s}, n) for s, n in stats["counts"].items()])
        lines += metrics.gauge_lines("kf_jobs_oldest_queued_seconds",
                                     "Age of the oldest queued job (0 when the queue is empty)",
                                     [({}, round(stats["oldest_queued_seconds"], 3))])
    except Exception as exc:
        logger.error("Metrics: queue stats unavailable: %s", type(exc).__name__)
    finally:
        db.close()
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
