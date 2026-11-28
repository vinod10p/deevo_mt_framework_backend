"""Live SQL Server: apply rbac_fix_04_default_member_role.sql (idempotent)."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from mtf.shared.database import engine
from tests.auth.test_rbac_fix_04 import FIX_PATH
from tests.sql_scripts import apply_sql_script

pytestmark = pytest.mark.integration


def _apply_fix() -> None:
    apply_sql_script(FIX_PATH)


@pytest.fixture(scope="module")
def applied() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1")).scalar()
    except DBAPIError as exc:
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    _apply_fix()


def test_column_exists_not_null_default_one(applied: None) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT c.is_nullable, dc.definition
                FROM sys.columns c
                LEFT JOIN sys.default_constraints dc ON dc.object_id = c.default_object_id
                WHERE c.object_id = OBJECT_ID('auth.tenant_user')
                  AND c.name = 'default_member_role_enabled'
                """
            )
        ).one()
    assert row.is_nullable is False or row.is_nullable == 0
    assert "1" in row.definition


def test_existing_rows_enabled(applied: None) -> None:
    with engine.connect() as conn:
        nulls = conn.execute(
            text(
                "SELECT COUNT(*) FROM auth.tenant_user WHERE default_member_role_enabled IS NULL"
            )
        ).scalar()
    assert nulls == 0


def test_rerun_is_noop(applied: None) -> None:
    _apply_fix()
