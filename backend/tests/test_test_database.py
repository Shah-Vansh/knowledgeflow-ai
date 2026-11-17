"""The test run must never touch the dev database."""
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.db.session import engine


def test_settings_point_at_a_test_database():
    assert make_url(settings.DATABASE_URL).database.endswith("_test")


def test_connected_database_is_the_test_database():
    with engine.connect() as conn:
        assert conn.execute(text("SELECT current_database()")).scalar().endswith("_test")


def test_test_database_is_migrated_to_head():
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0011"


def test_auth_is_off_by_default_in_tests():
    assert settings.AUTH_REQUIRED is False
