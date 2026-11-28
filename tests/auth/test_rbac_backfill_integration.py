"""Apply sql/auth_rbac_backfill_v3.sql on live SQL Server and prove the dual-write map."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user import User
from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.shared.database import SessionLocal, engine
from mtf.shared.deps import CurrentUser
from tests.auth.test_rbac_backfill import BACKFILL_PATH
from tests.auth.test_rbac_seed_integration import _apply_seed
from tests.sql_scripts import apply_sql_script

pytestmark = pytest.mark.integration




def _apply_backfill() -> None:
    apply_sql_script(BACKFILL_PATH)


def _live_count(sql: str) -> int:
    with SessionLocal() as db:
        return db.execute(text(sql)).scalar_one()


@pytest.fixture(scope="module")
def backfilled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    try:
        with engine.connect() as conn:
            present = conn.execute(text("SELECT OBJECT_ID('auth.user_role', 'U')")).scalar()
    except DBAPIError as exc:
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    if present is None:
        pytest.skip("auth.user_role is not present; apply sql/auth_rbac_schema_v3.sql")
    _apply_seed()
    _apply_backfill()


def test_every_live_tenant_user_has_user_role(backfilled: None) -> None:
    with SessionLocal() as db:
        missing = db.execute(
            text(
                """
                SELECT tu.id
                FROM auth.tenant_user tu
                JOIN tenant.tenant t ON t.id = tu.tenant_id AND t.is_deleted = 0
                WHERE tu.is_deleted = 0
                  AND NOT EXISTS (
                        SELECT 1
                        FROM auth.user_role ur
                        WHERE ur.tenant_id = tu.tenant_id
                          AND ur.user_id = tu.user_id
                          AND ur.account_id IS NULL
                          AND ur.is_deleted = 0
                  )
                """
            )
        ).fetchall()
    assert missing == []


def test_every_live_account_user_has_user_role(backfilled: None) -> None:
    with SessionLocal() as db:
        missing = db.execute(
            text(
                """
                SELECT tau.id
                FROM auth.tenant_account_user tau
                JOIN tenant.tenant t ON t.id = tau.tenant_id AND t.is_deleted = 0
                WHERE tau.is_deleted = 0
                  AND NOT EXISTS (
                        SELECT 1
                        FROM auth.user_role ur
                        WHERE ur.tenant_id = tau.tenant_id
                          AND ur.user_id = tau.user_id
                          AND ur.account_id = tau.account_id
                          AND ur.is_deleted = 0
                  )
                """
            )
        ).fetchall()
    assert missing == []


def test_membership_roles_map_to_template_codes(backfilled: None) -> None:
    with SessionLocal() as db:
        tenant_rows = db.execute(
            text(
                """
                SELECT tu.role, r.code
                FROM auth.tenant_user tu
                JOIN auth.user_role ur
                    ON ur.tenant_id = tu.tenant_id
                   AND ur.user_id = tu.user_id
                   AND ur.account_id IS NULL
                   AND ur.is_deleted = 0
                JOIN auth.role r ON r.id = ur.role_id
                  AND r.tenant_id IS NULL
                  AND r.code = 'tenant_admin'
                WHERE tu.is_deleted = 0
                """
            )
        ).all()
        portal_rows = db.execute(
            text(
                """
                SELECT tau.role, r.code
                FROM auth.tenant_account_user tau
                JOIN auth.user_role ur
                    ON ur.tenant_id = tau.tenant_id
                   AND ur.user_id = tau.user_id
                   AND ur.account_id = tau.account_id
                   AND ur.is_deleted = 0
                JOIN auth.role r ON r.id = ur.role_id
                  AND r.tenant_id IS NULL
                  AND r.code IN ('account_admin', 'account_member')
                WHERE tau.is_deleted = 0
                """
            )
        ).all()
    assert tenant_rows
    for membership_role, code in tenant_rows:
        # Members have no template row; this query only joins live template assignments.
        assert code == "tenant_admin"
        assert membership_role == "admin"
    for membership_role, code in portal_rows:
        expected = "account_admin" if membership_role == "admin" else "account_member"
        assert code == expected


def test_role_report_copied_for_live_tenants(backfilled: None) -> None:
    tenants = _live_count("SELECT COUNT(*) FROM tenant.tenant WHERE is_deleted = 0")
    defaults = _live_count(
        "SELECT COUNT(*) FROM auth.default_role_report WHERE is_deleted = 0 AND is_active = 1"
    )
    reports = _live_count("SELECT COUNT(*) FROM auth.role_report WHERE is_deleted = 0")
    assert tenants > 0 and defaults > 0
    assert reports >= tenants * defaults


def test_owner_resolves_lead_and_role_update(backfilled: None) -> None:
    with SessionLocal() as db:
        membership = db.scalars(
            select(TenantUser).where(
                TenantUser.is_deleted == False,  # noqa: E712
                TenantUser.is_active == True,  # noqa: E712
                TenantUser.role == "admin",
            )
        ).first()
        if membership is None:
            pytest.skip("no live owner/admin tenant_user")
        user = db.get(User, membership.user_id)
        assert user is not None
        actor = CurrentUser(
            user_id=membership.user_id,
            user_type="app_user",
            user_scope="tenant",
            tenant_id=membership.tenant_id,
        )
        codes = PermissionResolver(db).permission_codes(actor)
    assert "screen.lead.view" in codes
    assert "screen.lead.create" in codes
    assert "api.auth.role.update" in codes


def test_member_resolves_lead_view_only(backfilled: None) -> None:
    with SessionLocal() as db:
        membership = db.scalars(
            select(TenantUser).where(
                TenantUser.is_deleted == False,  # noqa: E712
                TenantUser.is_active == True,  # noqa: E712
                TenantUser.role == "member",
            )
        ).first()
        if membership is None:
            pytest.skip("no live member tenant_user")
        actor = CurrentUser(
            user_id=membership.user_id,
            user_type="app_user",
            user_scope="tenant",
            tenant_id=membership.tenant_id,
        )
        codes = PermissionResolver(db).permission_codes(actor)
    assert "screen.lead.view" in codes
    assert "screen.lead.create" not in codes
    assert "api.auth.role.update" not in codes


def test_every_live_tenant_has_screens_flag(backfilled: None) -> None:
    with SessionLocal() as db:
        missing = db.execute(
            text(
                """
                SELECT t.id
                FROM tenant.tenant t
                WHERE t.is_deleted = 0
                  AND NOT EXISTS (
                        SELECT 1
                        FROM tenant.tenant_setting s
                        WHERE s.tenant_id = t.id
                          AND s.[key] = 'rbac.screens'
                          AND s.[value] = N'on'
                          AND s.is_deleted = 0
                  )
                """
            )
        ).fetchall()
    assert missing == []


def test_backfill_is_idempotent(backfilled: None) -> None:
    before_roles = _live_count("SELECT COUNT(*) FROM auth.user_role WHERE is_deleted = 0")
    before_reports = _live_count("SELECT COUNT(*) FROM auth.role_report WHERE is_deleted = 0")
    before_flags = _live_count(
        "SELECT COUNT(*) FROM tenant.tenant_setting "
        "WHERE [key] = 'rbac.screens' AND is_deleted = 0"
    )
    _apply_backfill()
    assert _live_count("SELECT COUNT(*) FROM auth.user_role WHERE is_deleted = 0") == before_roles
    reports_after = _live_count("SELECT COUNT(*) FROM auth.role_report WHERE is_deleted = 0")
    assert reports_after == before_reports
    assert (
        _live_count(
            "SELECT COUNT(*) FROM tenant.tenant_setting "
            "WHERE [key] = 'rbac.screens' AND is_deleted = 0"
        )
        == before_flags
    )
