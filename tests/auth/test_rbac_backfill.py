"""auth_rbac_backfill_v3.sql — dual-write map, fail-fast, insert-missing only."""

from __future__ import annotations

from pathlib import Path

BACKFILL_PATH = Path(__file__).resolve().parents[2] / "sql" / "auth_rbac_backfill_v3.sql"


def _sql() -> str:
    return BACKFILL_PATH.read_text(encoding="utf-8")


def test_backfill_file_exists() -> None:
    assert BACKFILL_PATH.is_file()


def test_backfill_requires_seeded_template_roles() -> None:
    sql = _sql()
    assert "THROW 50010" in sql
    for code in ("tenant_admin", "tenant_member", "account_admin", "account_member"):
        assert f"code = '{code}'" in sql


def test_backfill_maps_membership_roles() -> None:
    sql = _sql()
    assert "THEN 'tenant_admin'" in sql
    assert "THEN 'tenant_member'" in sql
    assert "THEN 'account_admin'" in sql
    assert "THEN 'account_member'" in sql
    assert "WHEN 'owner'" in sql
    assert "WHEN 'viewer'" in sql
    assert "THROW 50011" in sql


def test_backfill_inserts_only_missing_rows() -> None:
    sql = _sql()
    assert sql.count("NOT EXISTS") >= 3
    assert "auth.role_report" in sql
    assert "auth.user_role" in sql
    assert "auth.default_role_report" in sql
    assert "01JRACBKF" in sql
    assert "NEWID()" not in sql.upper()
