"""sql/rbac_fix_03_screens_flag.sql — static checks (no database)."""

from __future__ import annotations

from pathlib import Path

FIX_PATH = Path(__file__).resolve().parents[2] / "sql" / "rbac_fix_03_screens_flag.sql"


def _sql() -> str:
    return FIX_PATH.read_text(encoding="utf-8")


def test_fix_file_exists() -> None:
    assert FIX_PATH.is_file()


def test_unique_index_is_filtered_live_rows() -> None:
    sql = _sql()
    assert "THROW 51030" in sql
    assert "UX_tenant_setting_tenant_key" in sql
    assert "UQ_tenant_setting_tenant_key" in sql
    assert "(tenant_id, [key])" in sql
    assert "WHERE is_deleted = 0" in sql


def test_rbac_screens_is_one_way() -> None:
    sql = _sql()
    assert "TR_tenant_setting_rbac_screens_one_way" in sql
    assert "THROW 51031" in sql
    assert "THROW 51032" in sql
    assert "rbac.screens" in sql
    assert "cannot be turned off" in sql
    assert "cannot be deleted" in sql


def test_fail_closes_live_tenants() -> None:
    sql = _sql()
    assert "INSERT INTO tenant.tenant_setting" in sql
    assert "N'on'" in sql
    assert "01JRACSTG" in sql
    assert "NEWID()" not in sql.upper()
