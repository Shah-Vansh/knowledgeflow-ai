import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.api import health

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="KnowledgeFlow AI", version="0.0.0-phase0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)


@app.on_event("startup")
def on_startup():
    logger.info("KnowledgeFlow AI backend starting up | environment=%s", settings.ENVIRONMENT)