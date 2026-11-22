"""sql/rbac_fix_01_tenant_integrity.sql — static checks (no database)."""

from __future__ import annotations

from pathlib import Path

FIX_PATH = Path(__file__).resolve().parents[2] / "sql" / "rbac_fix_01_tenant_integrity.sql"


def _sql() -> str:
    return FIX_PATH.read_text(encoding="utf-8")


def test_fix_file_exists() -> None:
    assert FIX_PATH.is_file()


def test_step_zero_aborts_on_violations() -> None:
    sql = _sql()
    assert "THROW 51000" in sql
    assert "soft-delete will not pass the FKs" in sql
    assert "STRING_AGG" in sql


def test_composite_account_tenant_foreign_keys() -> None:
    sql = _sql()
    assert "UQ_tenant_account_id_tenant_id" in sql
    assert "FK_user_role_account_tenant" in sql
    assert "FK_tenant_account_user_account_tenant" in sql
    assert "FK_user_role_account_id" in sql
    assert "FK_tenant_account_user_account_id" in sql


def test_triggers_set_xact_abort_and_error_numbers() -> None:
    sql = _sql()
    assert sql.upper().count("SET XACT_ABORT ON") >= 5
    for code in (
        "51001",
        "51002",
        "51003",
        "51004",
        "51005",
        "51006",
        "51007",
        "51008",
        "51009",
        "51010",
    ):
        assert f"THROW {code}" in sql
    assert "UPDATE(user_scope)" in sql
    assert "TR_user_role_integrity" in sql
    assert "TR_role_report_integrity" in sql
    assert "TR_default_role_report_integrity" in sql
    assert "TR_role_tenant_immutable" in sql
    assert "TR_report_definition_scope_guard" in sql
