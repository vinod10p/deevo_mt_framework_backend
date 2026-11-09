"""Onboarding copy of default_role_report and dual-write to user_role."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from mtf.audit.models import AuditLog
from mtf.auth.models.default_role_report import DefaultRoleReport
from mtf.auth.models.role import Role
from mtf.auth.models.role_report import RoleReport
from mtf.auth.models.user_role import UserRole
from mtf.auth.schemas.tenant_user import TenantMembershipCreate
from mtf.auth.services.membership_rbac import (
    ACCOUNT_MEMBERSHIP_ROLE_MAP,
    TENANT_MEMBERSHIP_ROLE_MAP,
    copy_default_role_reports,
    revoke_account_user_roles,
    revoke_tenant_user_roles,
    sync_account_user_role,
    sync_tenant_user_role,
    template_role_code,
)
from mtf.auth.services.tenant_account_user import TenantAccountUserService
from mtf.auth.services.tenant_user import TenantUserService
from mtf.tenant.schemas import TenantCreate, TenantUserCreate
from mtf.tenant.schemas.tenant_account_user import TenantAccountUserCreate
from mtf.tenant.services.tenant_service import TenantService
from tests.tenant.conftest import TEST_ACCOUNT_ID, TEST_TENANT_ID, TEST_USER_ID

_ROLE_ADMIN_ID = "01JRACMTFR1000000000000001"
_ROLE_MEMBER_ID = "01JRACMTFR1000000000000002"
_REPORT_ID = "01JRACMTFREPORT00000000001"


def _role(*, code: str = "tenant_admin", user_scope: str = "tenant") -> Role:
    role_id = _ROLE_ADMIN_ID if code.endswith("admin") else _ROLE_MEMBER_ID
    return Role(
        id=role_id,
        code=code,
        name=code.replace("_", " ").title(),
        user_scope=user_scope,
        tenant_id=None,
        is_system=True,
        is_active=True,
        is_deleted=False,
    )


def _user_role(*, role_id: str = _ROLE_ADMIN_ID) -> UserRole:
    return UserRole(
        id="01JRACUSRROLE0000000000001",
        tenant_id=TEST_TENANT_ID,
        user_id=TEST_USER_ID,
        account_id=None,
        role_id=role_id,
        user_scope="tenant",
        is_active=True,
        is_deleted=False,
        created_by=TEST_USER_ID,
    )


def _added(db: MagicMock, model: type) -> list:
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], model)]


def test_dual_write_map_covers_membership_roles() -> None:
    assert TENANT_MEMBERSHIP_ROLE_MAP == {
        "owner": "tenant_admin",
        "admin": "tenant_admin",
        "member": "tenant_member",
        "viewer": "tenant_member",
    }
    assert ACCOUNT_MEMBERSHIP_ROLE_MAP == {
        "admin": "account_admin",
        "member": "account_member",
    }
    assert template_role_code(user_scope="tenant", membership_role="owner") == (
        "tenant_admin"
    )
    assert template_role_code(user_scope="tenant", membership_role="viewer") == (
        "tenant_member"
    )
    assert template_role_code(
        user_scope="tenant_account",
        membership_role="admin",
    ) == "account_admin"


def test_unknown_membership_role_is_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        template_role_code(user_scope="tenant", membership_role="superuser")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "AUTH_ROLE_BAD_REQUEST"


def test_missing_platform_role_is_409() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = None
    with pytest.raises(HTTPException) as exc_info:
        sync_tenant_user_role(
            db,
            tenant_id=TEST_TENANT_ID,
            user_id=TEST_USER_ID,
            membership_role="owner",
            actor_id=TEST_USER_ID,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "AUTH_ROLE_CONFLICT"
    assert "tenant_admin" in exc_info.value.detail["message"]


def test_sync_inserts_user_role_for_owner() -> None:
    db = MagicMock()
    role = _role()
    db.scalars.side_effect = [
        MagicMock(first=MagicMock(return_value=role)),
        MagicMock(all=MagicMock(return_value=[])),
    ]
    sync_tenant_user_role(
        db,
        tenant_id=TEST_TENANT_ID,
        user_id=TEST_USER_ID,
        membership_role="owner",
        actor_id=TEST_USER_ID,
    )
    [assignment] = _added(db, UserRole)
    assert assignment.role_id == role.id
    assert assignment.user_scope == "tenant"
    assert assignment.account_id is None
    assert assignment.is_active is True
    logs = _added(db, AuditLog)
    assert any(
        log.table_name == "user_role" and log.action == "insert" for log in logs
    )


def test_sync_replaces_assignment_when_role_changes() -> None:
    db = MagicMock()
    member_role = _role(code="tenant_member")
    previous = _user_role(role_id=_ROLE_ADMIN_ID)
    db.scalars.side_effect = [
        MagicMock(first=MagicMock(return_value=member_role)),
        MagicMock(all=MagicMock(return_value=[previous])),
    ]
    sync_tenant_user_role(
        db,
        tenant_id=TEST_TENANT_ID,
        user_id=TEST_USER_ID,
        membership_role="member",
        actor_id=TEST_USER_ID,
    )
    assert previous.is_deleted is True
    assert previous.deleted_by == TEST_USER_ID
    assert previous.deleted_at is not None
    inserted = [row for row in _added(db, UserRole) if not row.is_deleted]
    assert len(inserted) == 1
    assert inserted[0].role_id == member_role.id
    assert inserted[0].id != previous.id


def test_sync_keeps_assignment_when_map_is_unchanged() -> None:
    db = MagicMock()
    admin_role = _role(code="tenant_admin")
    existing = _user_role(role_id=admin_role.id)
    db.scalars.side_effect = [
        MagicMock(first=MagicMock(return_value=admin_role)),
        MagicMock(all=MagicMock(return_value=[existing])),
    ]
    sync_tenant_user_role(
        db,
        tenant_id=TEST_TENANT_ID,
        user_id=TEST_USER_ID,
        membership_role="admin",
        actor_id=TEST_USER_ID,
    )
    assert existing.is_deleted is False
    assert [row.role_id for row in _added(db, UserRole)] == [admin_role.id]


def test_sync_only_replaces_platform_template_roles() -> None:
    db = MagicMock()
    db.scalars.side_effect = [
        MagicMock(first=MagicMock(return_value=_role(code="tenant_member"))),
        MagicMock(all=MagicMock(return_value=[])),
    ]
    sync_tenant_user_role(
        db,
        tenant_id=TEST_TENANT_ID,
        user_id=TEST_USER_ID,
        membership_role="member",
        actor_id=TEST_USER_ID,
    )
    live_stmt = db.scalars.call_args_list[1].args[0]
    sql = str(live_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "JOIN auth.role" in sql
    assert "auth.role.tenant_id IS NULL" in sql
    assert "'tenant_admin'" in sql and "'tenant_member'" in sql


def test_revoke_does_not_filter_to_template_roles() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    revoke_tenant_user_roles(
        db,
        tenant_id=TEST_TENANT_ID,
        user_id=TEST_USER_ID,
        actor_id=TEST_USER_ID,
    )
    sql = str(db.scalars.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "JOIN auth.role" not in sql


def test_revoke_soft_deletes_live_assignments() -> None:
    db = MagicMock()
    row = _user_role()
    db.scalars.return_value.all.return_value = [row]
    revoke_tenant_user_roles(
        db,
        tenant_id=TEST_TENANT_ID,
        user_id=TEST_USER_ID,
        actor_id=TEST_USER_ID,
    )
    assert row.is_deleted is True
    assert row.is_active is False
    assert row.deleted_by == TEST_USER_ID
    logs = _added(db, AuditLog)
    assert any(
        log.table_name == "user_role" and log.action == "delete" for log in logs
    )


def test_account_sync_sets_account_id_and_scope() -> None:
    db = MagicMock()
    role = _role(code="account_member", user_scope="tenant_account")
    db.scalars.side_effect = [
        MagicMock(first=MagicMock(return_value=role)),
        MagicMock(all=MagicMock(return_value=[])),
    ]
    sync_account_user_role(
        db,
        tenant_id=TEST_TENANT_ID,
        account_id=TEST_ACCOUNT_ID,
        user_id=TEST_USER_ID,
        membership_role="member",
        actor_id=TEST_USER_ID,
    )
    [assignment] = _added(db, UserRole)
    assert assignment.account_id == TEST_ACCOUNT_ID
    assert assignment.user_scope == "tenant_account"
    assert assignment.role_id == role.id


def test_copy_default_role_reports_inserts_missing_rows() -> None:
    db = MagicMock()
    default = DefaultRoleReport(
        id="01JRACDFLT0000000000000001",
        role_id=_ROLE_ADMIN_ID,
        report_id=_REPORT_ID,
        can_view=True,
        can_export=True,
        is_active=True,
        is_deleted=False,
    )
    db.scalars.side_effect = [
        MagicMock(all=MagicMock(return_value=[default])),
        MagicMock(all=MagicMock(return_value=[])),
    ]
    inserted = copy_default_role_reports(
        db,
        tenant_id=TEST_TENANT_ID,
        created_by=TEST_USER_ID,
    )
    assert inserted == 1
    [grant] = _added(db, RoleReport)
    assert grant.tenant_id == TEST_TENANT_ID
    assert grant.role_id == default.role_id
    assert grant.report_id == default.report_id
    assert grant.can_export is True
    logs = _added(db, AuditLog)
    assert any(
        log.table_name == "role_report" and log.action == "insert" for log in logs
    )


def test_copy_default_role_reports_skips_existing_pairs() -> None:
    db = MagicMock()
    default = DefaultRoleReport(
        id="01JRACDFLT0000000000000001",
        role_id=_ROLE_ADMIN_ID,
        report_id=_REPORT_ID,
        can_view=True,
        can_export=False,
        is_active=True,
        is_deleted=False,
    )
    existing = RoleReport(
        id="01JRACRPT00000000000000001",
        tenant_id=TEST_TENANT_ID,
        role_id=_ROLE_ADMIN_ID,
        report_id=_REPORT_ID,
        can_view=True,
        can_export=False,
        is_deleted=False,
    )
    db.scalars.side_effect = [
        MagicMock(all=MagicMock(return_value=[default])),
        MagicMock(all=MagicMock(return_value=[existing])),
    ]
    assert copy_default_role_reports(db, tenant_id=TEST_TENANT_ID) == 0
    assert _added(db, RoleReport) == []


def test_create_tenant_copies_defaults_before_commit() -> None:
    db = MagicMock()
    with patch(
        "mtf.tenant.services.tenant_service.copy_default_role_reports",
    ) as copy_fn:
        tenant = TenantService(db).create_tenant(
            TenantCreate(name="Co", subdomain="co"),
            created_by=TEST_USER_ID,
        )
    copy_fn.assert_called_once()
    assert copy_fn.call_args.kwargs["tenant_id"] == tenant.id
    assert copy_fn.call_args.kwargs["created_by"] == TEST_USER_ID
    db.commit.assert_called_once()


def test_tenant_membership_mutations_dual_write() -> None:
    db = MagicMock()
    svc = TenantUserService(db)
    payload = TenantUserCreate(
        email="new@example.com",
        password="password123",
        role="member",
    )
    with (
        patch.object(svc, "_require_tenant"),
        patch.object(svc, "_get_active_user_by_email", return_value=None),
        patch("mtf.auth.services.tenant_user.hash_password", return_value="h"),
        patch("mtf.auth.services.tenant_user.sync_tenant_user_role") as sync,
    ):
        svc.create_for_tenant(TEST_TENANT_ID, payload, created_by=TEST_USER_ID)
    sync.assert_called_once()
    assert sync.call_args.kwargs["tenant_id"] == TEST_TENANT_ID
    assert sync.call_args.kwargs["membership_role"] == "member"

    row = MagicMock()
    row.tenant_id = TEST_TENANT_ID
    row.user_id = TEST_USER_ID
    row.role = "member"
    row.is_active = True
    row.is_deleted = False
    with patch(
        "mtf.auth.services.tenant_user.sync_tenant_user_role",
    ) as sync_link:
        db.scalars.return_value.first.return_value = MagicMock(
            user_scope="tenant",
            is_deleted=False,
        )
        with patch.object(svc, "_require_tenant"), patch.object(
            svc,
            "_existing_membership",
            return_value=None,
        ):
            svc.create(
                TenantMembershipCreate(
                    tenant_id=TEST_TENANT_ID,
                    user_id=TEST_USER_ID,
                    role="admin",
                ),
                created_by=TEST_USER_ID,
            )
    sync_link.assert_called_once()
    assert sync_link.call_args.kwargs["membership_role"] == "admin"


def test_account_membership_mutations_dual_write() -> None:
    db = MagicMock()
    svc = TenantAccountUserService(db)
    payload = TenantAccountUserCreate(
        email="portal@example.com",
        password="password123",
        role="admin",
    )
    with (
        patch.object(svc, "_require_account"),
        patch.object(svc, "_get_active_user_by_email", return_value=None),
        patch(
            "mtf.auth.services.tenant_account_user.hash_password",
            return_value="h",
        ),
        patch(
            "mtf.auth.services.tenant_account_user.sync_account_user_role",
        ) as sync,
    ):
        svc.create_for_account(
            TEST_TENANT_ID,
            TEST_ACCOUNT_ID,
            payload,
            created_by=TEST_USER_ID,
        )
    sync.assert_called_once()
    assert sync.call_args.kwargs["account_id"] == TEST_ACCOUNT_ID
    assert sync.call_args.kwargs["membership_role"] == "admin"

    membership = MagicMock()
    membership.role = "member"
    with (
        patch.object(svc, "_membership", return_value=membership),
        patch(
            "mtf.auth.services.tenant_account_user.revoke_account_user_roles",
        ) as revoke,
    ):
        svc.soft_delete_for_account(
            TEST_TENANT_ID,
            TEST_ACCOUNT_ID,
            TEST_USER_ID,
            deleted_by=TEST_USER_ID,
        )
    revoke.assert_called_once()
    assert revoke.call_args.kwargs["account_id"] == TEST_ACCOUNT_ID


def test_revoke_account_helper_is_exported() -> None:
    """Sanity: portal revoke shares the same place-filter path."""
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    revoke_account_user_roles(
        db,
        tenant_id=TEST_TENANT_ID,
        account_id=TEST_ACCOUNT_ID,
        user_id=TEST_USER_ID,
        actor_id=TEST_USER_ID,
    )
    db.scalars.assert_called_once()
