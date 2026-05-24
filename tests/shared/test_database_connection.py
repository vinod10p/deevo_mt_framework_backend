"""Live SQL Server connectivity check using `app.shared` settings (loads `.env`).

Run locally after configuring `.env`:

    uv run pytest tests/shared/test_database_connection.py -v

Skip in CI or when no database is available:

    DEEVO_SKIP_DB_TESTS=1 uv run pytest tests/shared/test_database_connection.py -v
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


@pytest.fixture
def engine():
    _skip_if_disabled()
    from mtf.shared.database import engine as db_engine

    return db_engine


def test_sql_server_select_one(engine) -> None:
    """Opens one connection and runs `SELECT 1` (validates ODBC + auth + reachability)."""
    with engine.connect() as conn:
        one = conn.execute(text("SELECT 1 AS one")).scalar_one()
    assert one == 1


def test_sql_server_database_name_matches_discrete_config(engine) -> None:
    """When using discrete `DEEVO_MSSQL_*` settings, current DB should match `DEEVO_MSSQL_DATABASE`."""
    from mtf.shared.config import get_settings

    settings = get_settings()
    if settings.database_url:
        pytest.skip("DEEVO_DATABASE_URL is set; discrete database name check not applied")

    with engine.connect() as conn:
        current = conn.execute(text("SELECT DB_NAME() AS n")).scalar_one()

    assert current is not None
    assert str(current).lower() == settings.mssql_database.lower()
