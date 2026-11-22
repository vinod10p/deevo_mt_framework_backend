"""sql/rbac_fix_05_admin_member_only.sql — static checks (no database)."""

from __future__ import annotations

from pathlib import Path

FIX_PATH = Path(__file__).resolve().parents[2] / "sql" / "rbac_fix_05_admin_member_only.sql"


def _sql() -> str:
    return FIX_PATH.read_text(encoding="utf-8")


def test_fix_file_exists() -> None:
    assert FIX_PATH.is_file()


def test_collapses_owner_viewer_and_narrows_ck() -> None:
    sql = _sql()
    assert "role = 'owner'" in sql
    assert "role = 'viewer'" in sql
    assert "CHECK ([role] IN ('admin', 'member'))" in sql


def test_thins_tenant_admin_and_empties_tenant_member() -> None:
    sql = _sql()
    for code in (
        "api.auth.role.update",
        "menu.admin_users.view",
        "menu.admin_portal_accounts.view",
    ):
        assert f"('{code}')" in sql
    assert "role_id = @R_TENANT_MEMBER" in sql
    assert "a@lg.com" in sql
