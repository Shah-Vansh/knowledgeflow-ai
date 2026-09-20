import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.session import check_db_connection

router = APIRouter()
logger = logging.getLogger(__name__)


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