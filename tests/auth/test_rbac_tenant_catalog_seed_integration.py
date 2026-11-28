"""Apply sql/auth_rbac_seed_tenant_catalog_v1.sql and prove the catalog shape."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.shared.database import SessionLocal, engine
from tests.auth.test_rbac_tenant_catalog_seed import EXPECTED_PERMISSIONS, SEED_PATH
from tests.sql_scripts import apply_sql_script

pytestmark = pytest.mark.integration

_CRM_VIEW = {
    "screen.lead.view",
    "screen.account.view",
    "screen.contact.view",
    "screen.opportunity.view",
    "screen.task.view",
    "screen.note.view",
}
_WF_VIEW = {
    "menu.wf_inbox.view",
    "menu.wf_mine.view",
    "menu.wf_all.view",
    "menu.wf_templates.view",
}




def _apply_seed() -> None:
    apply_sql_script(SEED_PATH)


@pytest.fixture(scope="module")
def seeded() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    try:
        with engine.connect() as conn:
            present = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM sys.columns
                    WHERE object_id = OBJECT_ID('auth.permission')
                      AND name = 'is_tenant_grantable'
                    """
                )
            ).scalar()
            admin = conn.execute(
                text(
                    """
                    SELECT 1 FROM auth.role
                    WHERE tenant_id IS NULL AND code = 'tenant_admin' AND is_deleted = 0
                    """
                )
            ).scalar()
    except DBAPIError as exc:
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    if present is None:
        pytest.skip("apply sql/rbac_fix_02_permission_catalog.sql first")
    if admin is None:
        pytest.skip("apply sql/auth_rbac_seed_v3.sql first")
    _apply_seed()


def _live_permissions() -> list[Permission]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(Permission).where(
                    Permission.is_deleted == False,  # noqa: E712
                    Permission.code.in_(EXPECTED_PERMISSIONS),
                )
            ).all()
        )


def _granted(role_code: str) -> set[str]:
    with SessionLocal() as db:
        role = db.scalars(
            select(Role).where(Role.tenant_id.is_(None), Role.code == role_code)
        ).one()
        return set(
            db.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(
                    RolePermission.role_id == role.id,
                    RolePermission.is_deleted == False,  # noqa: E712
                    Permission.is_deleted == False,  # noqa: E712
                )
            ).all()
        )


def test_catalog_rows_have_modules_and_flags(seeded: None) -> None:
    rows = {row.code: row for row in _live_permissions()}
    assert EXPECTED_PERMISSIONS <= set(rows)
    for code, row in rows.items():
        if code.startswith("screen."):
            assert row.module_code == "CRM"
            assert row.resource_type == "screen"
            assert row.user_scope == "tenant"
            assert row.is_tenant_grantable is True
        elif code.startswith("menu."):
            assert row.module_code == "WF"
            assert row.resource_type == "menu"
            assert row.action == "view"
            assert row.is_tenant_grantable is True
        elif code == "api.auth.role.update":
            assert row.module_code == "GENERAL"
            assert row.resource_name == "Tenant roles"
            assert row.is_tenant_grantable is True
        elif code == "api.system.role.update":
            assert row.module_code == "GENERAL"
            assert row.resource_name == "System roles"
            assert row.is_tenant_grantable is False
            assert row.user_scope == "system"


def test_tenant_admin_is_thin_admin_bundle(seeded: None) -> None:
    granted = _granted("tenant_admin")
    assert "api.auth.role.update" in granted
    assert "api.system.role.update" not in granted
    assert "menu.wf_inbox.view" not in granted
    assert "screen.account.create" not in granted
    # Admin menus come from nav_menu_fix_01 (may already be applied on this DB).
    assert granted <= {
        "api.auth.role.update",
        "menu.admin_users.view",
        "menu.admin_portal_accounts.view",
    }


def test_tenant_member_holds_no_grants(seeded: None) -> None:
    granted = _granted("tenant_member")
    assert granted == set()


def test_seed_is_idempotent(seeded: None) -> None:
    def _counts() -> tuple[int, int]:
        with SessionLocal() as db:
            perms = db.execute(
                text("SELECT COUNT(*) FROM auth.permission WHERE is_deleted = 0")
            ).scalar_one()
            grants = db.execute(
                text("SELECT COUNT(*) FROM auth.role_permission WHERE is_deleted = 0")
            ).scalar_one()
            return perms, grants

    before = _counts()
    _apply_seed()
    assert _counts() == before
