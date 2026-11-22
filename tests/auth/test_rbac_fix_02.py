"""sql/rbac_fix_02_permission_catalog.sql — static checks (no database)."""

from __future__ import annotations

from pathlib import Path

FIX_PATH = Path(__file__).resolve().parents[2] / "sql" / "rbac_fix_02_permission_catalog.sql"


def _sql() -> str:
    return FIX_PATH.read_text(encoding="utf-8")


def test_fix_file_exists() -> None:
    assert FIX_PATH.is_file()


def test_step_zero_aborts_on_duplicate_scope_code() -> None:
    sql = _sql()
    assert "THROW 51000" in sql
    assert "duplicate live (user_scope, code)" in sql
    assert "STRING_AGG" in sql


def test_adds_catalog_columns_and_checks() -> None:
    sql = _sql()
    assert "module_code" in sql
    assert "resource_name" in sql
    assert "sort_order" in sql
    assert "is_tenant_grantable" in sql
    assert "CK_permission_module_code_upper" in sql
    assert "CK_permission_system_not_grantable" in sql
    assert "DF_permission_module_code_tmp" in sql
    assert "user_scope = 'system' AND is_tenant_grantable = 1" in sql


def test_does_not_compute_code_or_add_source_role() -> None:
    sql = _sql()
    assert "ADD code AS" not in sql
    assert "CK_permission_code_format" not in sql
    assert "ALTER TABLE auth.role ADD source_role_id" not in sql
    assert "TR_role_source_integrity" not in sql


def test_unique_index_is_per_scope() -> None:
    sql = _sql()
    assert "DROP INDEX UQ_permission_code" in sql
    assert "UQ_permission_scope_code" in sql
    assert "(user_scope, code)" in sql
    assert "IX_permission_admin_grid" in sql
