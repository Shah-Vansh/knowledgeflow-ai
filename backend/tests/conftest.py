"""
Test bootstrap: every test runs against a SEPARATE database, never the dev one.

This module runs before any `app` import (pytest loads conftest.py first), so the
environment set here is what app.core.config.Settings reads.

  * DATABASE_URL comes from the environment or backend/.env; the test database is
    TEST_DATABASE_URL if set, otherwise the same server with "<name>_test".
  * The database is created if missing and migrated with `alembic upgrade head`.
  * Tests refuse to run unless the database name ends in "_test"
    (escape hatch: KF_ALLOW_NON_TEST_DB=1 — don't).
  * KF_TEST_DB_RECREATE=1 drops and recreates the test database first.
"""
import os
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("DATABASE_URL") or dotenv_values(BACKEND_DIR / ".env").get("DATABASE_URL")
    if not base:
        raise RuntimeError("DATABASE_URL is not set (environment or backend/.env); cannot derive the test database")
    url = make_url(base)
    name = url.database or ""
    if not name.endswith("_test"):
        url = url.set(database=f"{name}_test")
    return url.render_as_string(hide_password=False)


def _ensure_database(url_string: str, recreate: bool) -> None:
    url = make_url(url_string)
    name = url.database
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).scalar()
            if exists and recreate:
                conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
                exists = False
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config()  # no ini file -> env.py skips fileConfig, test logging stays intact
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


TEST_DATABASE_URL = _resolve_test_database_url()
TEST_DATABASE_NAME = make_url(TEST_DATABASE_URL).database or ""
if not TEST_DATABASE_NAME.endswith("_test") and not _truthy(os.environ.get("KF_ALLOW_NON_TEST_DB")):
    raise RuntimeError(
        f"Refusing to run tests against database {TEST_DATABASE_NAME!r}: the name must end in '_test'."
    )

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# Test defaults: auth OFF (auth tests switch it on per test), a long throwaway JWT
# secret, and cheap Argon2 parameters so hashing doesn't dominate the run.
os.environ["AUTH_REQUIRED"] = "false"
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-0123456789abcdefghijklmnopqrstuvwxyz")
os.environ["PASSWORD_HASH_TIME_COST"] = "1"
os.environ["PASSWORD_HASH_MEMORY_KIB"] = "1024"

_ensure_database(TEST_DATABASE_URL, recreate=_truthy(os.environ.get("KF_TEST_DB_RECREATE")))
_migrate()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    try:
        from app.core import ratelimit
    except ImportError:  # before Phase 15 code exists
        yield
        return
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def client():
    return TestClient(app)
