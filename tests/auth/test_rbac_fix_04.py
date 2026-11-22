"""sql/rbac_fix_04_default_member_role.sql — static checks (no database)."""

from __future__ import annotations

from pathlib import Path

FIX_PATH = Path(__file__).resolve().parents[2] / "sql" / "rbac_fix_04_default_member_role.sql"


def _sql() -> str:
    return FIX_PATH.read_text(encoding="utf-8")


def test_fix_file_exists() -> None:
    assert FIX_PATH.is_file()


def test_adds_non_null_flag_defaulting_on() -> None:
    sql = " ".join(_sql().split())
    assert "COL_LENGTH('auth.tenant_user', 'default_member_role_enabled') IS NULL" in sql
    assert "default_member_role_enabled bit NOT NULL" in sql
    assert "CONSTRAINT DF_tenant_user_default_member_role_enabled DEFAULT (1)" in sql
    assert "WITH VALUES" in sql


def test_does_not_touch_assignments() -> None:
    sql = _sql()
    assert "auth.user_role" not in sql.split("*/", 1)[1]
