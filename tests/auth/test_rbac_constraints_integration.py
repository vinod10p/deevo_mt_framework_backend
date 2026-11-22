"""Live SQL Server tests for RBAC v3 composite FKs and check constraints.

Every write is rolled back. Skip if ``DEEVO_SKIP_DB_TESTS`` is set or if
``auth.permission`` is not on the connected database (apply
``sql/auth_rbac_schema_v3.sql`` first).
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from mtf.auth.models.default_role_report import DefaultRoleReport
from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.auth.models.role_report import RoleReport
from mtf.auth.models.tenant_account_user import TenantAccountUser
from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user import User
from mtf.auth.models.user_role import UserRole
from mtf.rpt.models.report_definition import ReportDefinition
from mtf.shared.database import SessionLocal
from mtf.shared.security import generate_id
from mtf.tenant.models.tenant_account import TenantAccount

pytestmark = pytest.mark.integration


@pytest.fixture
def db() -> Generator[Session, None, None]:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    session = SessionLocal()
    try:
        session.execute(select(1))
        present = session.execute(text("SELECT OBJECT_ID('auth.permission', 'U')")).scalar()
    except DBAPIError as exc:
        session.close()
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    if present is None:
        session.close()
        pytest.skip("auth.permission is not present; apply sql/auth_rbac_schema_v3.sql")
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def membership(db: Session) -> TenantUser:
    row = db.scalars(
        select(TenantUser).where(
            TenantUser.is_deleted == False,  # noqa: E712
            TenantUser.is_active == True,  # noqa: E712
        )
    ).first()
    if row is None:
        pytest.skip("no live tenant_user row")
    user = db.get(User, row.user_id)
    if user is None or user.user_scope != "tenant":
        pytest.skip("tenant_user is not linked to a tenant-scope app_user")
    return row


def _permission(*, user_scope: str, action: str = "view") -> Permission:
    token = generate_id()[:10].lower()
    resource_code = f"pytest_{token}"
    return Permission(
        id=generate_id(),
        code=f"screen.{resource_code}.{action}",
        resource_type="screen",
        resource_code=resource_code,
        action=action,
        user_scope=user_scope,
        module_code="GENERAL",
        resource_name=resource_code,
        is_tenant_grantable=user_scope != "system",
    )


def _role(*, user_scope: str, tenant_id: str | None, is_system: bool) -> Role:
    token = generate_id()[:10].lower()
    return Role(
        id=generate_id(),
        tenant_id=tenant_id,
        code=f"pytest_{token}",
        name=f"pytest {token}",
        user_scope=user_scope,
        is_system=is_system,
    )


def test_matching_scope_role_permission_inserts(db: Session, membership: TenantUser) -> None:
    permission = _permission(user_scope="tenant")
    role = _role(user_scope="tenant", tenant_id=membership.tenant_id, is_system=False)
    db.add(permission)
    db.add(role)
    db.flush()
    grant = RolePermission(
        id=generate_id(),
        role_id=role.id,
        permission_id=permission.id,
        user_scope="tenant",
    )
    db.add(grant)
    db.flush()
    db.refresh(grant)
    assert grant.row_version
    assert grant.is_active is True
    assert grant.is_deleted is False


def test_cross_scope_role_permission_is_rejected(db: Session, membership: TenantUser) -> None:
    system_permission = _permission(user_scope="system")
    tenant_role = _role(user_scope="tenant", tenant_id=membership.tenant_id, is_system=False)
    db.add(system_permission)
    db.add(tenant_role)
    db.flush()
    db.add(
        RolePermission(
            id=generate_id(),
            role_id=tenant_role.id,
            permission_id=system_permission.id,
            user_scope="tenant",
        )
    )
    with pytest.raises(IntegrityError) as exc_info:
        db.flush()
    assert "FK_role_permission_permission_id" in str(exc_info.value.orig)


def test_user_role_scope_shape_rejects_tenant_id_on_system(
    db: Session, membership: TenantUser
) -> None:
    role = _role(user_scope="system", tenant_id=None, is_system=True)
    db.add(role)
    db.flush()
    system_user = db.scalars(
        select(User).where(
            User.user_scope == "system",
            User.is_deleted == False,  # noqa: E712
        )
    ).first()
    if system_user is None:
        pytest.skip("no live system app_user")
    db.add(
        UserRole(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            user_id=system_user.id,
            account_id=None,
            role_id=role.id,
            user_scope="system",
        )
    )
    with pytest.raises(IntegrityError) as exc_info:
        db.flush()
    assert "CK_user_role_scope_shape" in str(exc_info.value.orig)


def test_role_report_export_requires_view(db: Session, membership: TenantUser) -> None:
    report = db.scalars(
        select(ReportDefinition).where(
            ReportDefinition.scope_type == "system",
            ReportDefinition.is_deleted == False,  # noqa: E712
        )
    ).first()
    if report is None:
        pytest.skip("no live system report_definition")
    role = _role(user_scope="tenant", tenant_id=membership.tenant_id, is_system=False)
    db.add(role)
    db.flush()
    db.add(
        RoleReport(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            role_id=role.id,
            report_id=report.id,
            can_view=False,
            can_export=True,
        )
    )
    with pytest.raises(IntegrityError) as exc_info:
        db.flush()
    assert "CK_role_report_export_needs_view" in str(exc_info.value.orig)


@pytest.fixture
def tenant_integrity(db: Session) -> Session:
    present = db.execute(text("SELECT OBJECT_ID('auth.TR_user_role_integrity', 'TR')")).scalar()
    if present is None:
        pytest.skip("apply sql/rbac_fix_01_tenant_integrity.sql first")
    return db


def _orig(exc: BaseException) -> str:
    return str(getattr(exc, "orig", exc))


def _new_user(db: Session, *, user_scope: str) -> User:
    user = User(
        id=generate_id(),
        email=f"pytest-{generate_id()[:12].lower()}@example.test",
        user_scope=user_scope,
    )
    db.add(user)
    db.flush()
    return user


def _system_report(db: Session) -> ReportDefinition:
    report = db.scalars(
        select(ReportDefinition).where(
            ReportDefinition.scope_type == "system",
            ReportDefinition.is_deleted == False,  # noqa: E712
        )
    ).first()
    if report is None:
        pytest.skip("no live system report_definition")
    return report


def _account_in_tenant(db: Session, tenant_id: str) -> TenantAccount:
    account = db.scalars(
        select(TenantAccount).where(
            TenantAccount.tenant_id == tenant_id,
            TenantAccount.is_deleted == False,  # noqa: E712
        )
    ).first()
    if account is None:
        pytest.skip("no live tenant_account for this tenant")
    return account


def _other_account(db: Session, tenant_id: str) -> TenantAccount:
    account = db.scalars(
        select(TenantAccount).where(
            TenantAccount.tenant_id != tenant_id,
            TenantAccount.is_deleted == False,  # noqa: E712
        )
    ).first()
    if account is None:
        pytest.skip("need a live tenant_account in another tenant")
    return account


def _platform_role(db: Session, *, code: str, user_scope: str) -> Role:
    role = db.scalars(
        select(Role).where(
            Role.tenant_id.is_(None),
            Role.code == code,
            Role.user_scope == user_scope,
            Role.is_deleted == False,  # noqa: E712
        )
    ).first()
    if role is None:
        pytest.skip(f"platform role {code!r} is not seeded")
    return role


def test_template_role_can_be_assigned_to_tenant_member(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    role = _role(user_scope="tenant", tenant_id=None, is_system=True)
    db.add(role)
    db.flush()
    db.add(
        UserRole(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            user_id=membership.user_id,
            account_id=None,
            role_id=role.id,
            user_scope="tenant",
        )
    )
    db.flush()


def test_user_role_rejects_deleted_role(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    role = _role(user_scope="tenant", tenant_id=membership.tenant_id, is_system=False)
    db.add(role)
    db.flush()
    role.is_deleted = True
    role.deleted_at = role.created_at
    role.deleted_by = membership.user_id
    db.flush()
    db.add(
        UserRole(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            user_id=membership.user_id,
            account_id=None,
            role_id=role.id,
            user_scope="tenant",
        )
    )
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51001" in _orig(exc_info.value)


def test_user_role_rejects_non_member(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    role = _role(user_scope="tenant", tenant_id=membership.tenant_id, is_system=False)
    outsider = _new_user(db, user_scope="tenant")
    db.add(role)
    db.flush()
    db.add(
        UserRole(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            user_id=outsider.id,
            account_id=None,
            role_id=role.id,
            user_scope="tenant",
        )
    )
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51002" in _orig(exc_info.value)


def test_user_role_rejects_portal_non_member(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    account = _account_in_tenant(db, membership.tenant_id)
    role = _platform_role(db, code="account_member", user_scope="tenant_account")
    outsider = _new_user(db, user_scope="tenant_account")
    db.add(
        UserRole(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            user_id=outsider.id,
            account_id=account.id,
            role_id=role.id,
            user_scope="tenant_account",
        )
    )
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51003" in _orig(exc_info.value)


def test_user_role_rejects_account_from_another_tenant(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    other = _other_account(db, membership.tenant_id)
    role = _platform_role(db, code="account_member", user_scope="tenant_account")
    portal = db.scalars(
        select(TenantAccountUser).where(
            TenantAccountUser.tenant_id == membership.tenant_id,
            TenantAccountUser.is_deleted == False,  # noqa: E712
        )
    ).first()
    if portal is None:
        pytest.skip("no live tenant_account_user for this tenant")
    db.add(
        UserRole(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            user_id=portal.user_id,
            account_id=other.id,
            role_id=role.id,
            user_scope="tenant_account",
        )
    )
    with pytest.raises(IntegrityError) as exc_info:
        db.flush()
    assert "FK_user_role_account_tenant" in _orig(exc_info.value)


def test_tenant_account_user_rejects_account_from_another_tenant(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    other = _other_account(db, membership.tenant_id)
    portal = _new_user(db, user_scope="tenant_account")
    db.add(
        TenantAccountUser(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            account_id=other.id,
            user_id=portal.id,
            role="member",
        )
    )
    with pytest.raises(IntegrityError) as exc_info:
        db.flush()
    assert "FK_tenant_account_user_account_tenant" in _orig(exc_info.value)


def test_role_report_allows_platform_template(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    report = _system_report(db)
    role = _platform_role(db, code="tenant_admin", user_scope="tenant")
    existing = db.scalars(
        select(RoleReport).where(
            RoleReport.tenant_id == membership.tenant_id,
            RoleReport.role_id == role.id,
            RoleReport.report_id == report.id,
            RoleReport.is_deleted == False,  # noqa: E712
        )
    ).first()
    if existing is not None:
        return
    db.add(
        RoleReport(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            role_id=role.id,
            report_id=report.id,
            can_view=True,
            can_export=False,
        )
    )
    db.flush()


def test_role_report_rejects_system_role(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    report = _system_report(db)
    role = _role(user_scope="system", tenant_id=None, is_system=True)
    db.add(role)
    db.flush()
    db.add(
        RoleReport(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            role_id=role.id,
            report_id=report.id,
            can_view=True,
            can_export=False,
        )
    )
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51004" in _orig(exc_info.value)


def test_role_report_rejects_other_tenant_report(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    other = _other_account(db, membership.tenant_id)
    role = _role(user_scope="tenant", tenant_id=membership.tenant_id, is_system=False)
    report = ReportDefinition(
        id=generate_id(),
        tenant_id=other.tenant_id,
        scope_type="tenant",
        report_key=f"pytest_{generate_id()[:10].lower()}",
        display_name="pytest other tenant report",
        proc_name="rpt.usp_pytest_unused",
    )
    db.add(role)
    db.add(report)
    db.flush()
    db.add(
        RoleReport(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            role_id=role.id,
            report_id=report.id,
            can_view=True,
            can_export=False,
        )
    )
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51005" in _orig(exc_info.value)


def test_default_role_report_rejects_tenant_owned_role(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    report = _system_report(db)
    role = _role(user_scope="tenant", tenant_id=membership.tenant_id, is_system=False)
    db.add(role)
    db.flush()
    db.add(
        DefaultRoleReport(
            id=generate_id(),
            role_id=role.id,
            report_id=report.id,
            can_view=True,
            can_export=False,
        )
    )
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51006" in _orig(exc_info.value)


def test_default_role_report_rejects_tenant_report(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    role = _platform_role(db, code="tenant_admin", user_scope="tenant")
    report = ReportDefinition(
        id=generate_id(),
        tenant_id=membership.tenant_id,
        scope_type="tenant",
        report_key=f"pytest_{generate_id()[:10].lower()}",
        display_name="pytest tenant report",
        proc_name="rpt.usp_pytest_unused",
    )
    db.add(report)
    db.flush()
    db.add(
        DefaultRoleReport(
            id=generate_id(),
            role_id=role.id,
            report_id=report.id,
            can_view=True,
            can_export=False,
        )
    )
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51007" in _orig(exc_info.value)


def test_role_tenant_id_is_immutable(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    role = _role(user_scope="tenant", tenant_id=membership.tenant_id, is_system=False)
    db.add(role)
    db.flush()
    role.tenant_id = None
    role.is_system = True
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51008" in _orig(exc_info.value)


def test_role_user_scope_is_immutable(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    role = _role(user_scope="tenant", tenant_id=membership.tenant_id, is_system=False)
    db.add(role)
    db.flush()
    role.user_scope = "tenant_account"
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51010" in _orig(exc_info.value)


def test_report_scope_guard_while_granted(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    role = _role(user_scope="tenant", tenant_id=membership.tenant_id, is_system=False)
    report = ReportDefinition(
        id=generate_id(),
        tenant_id=membership.tenant_id,
        scope_type="tenant",
        report_key=f"pytest_{generate_id()[:10].lower()}",
        display_name="pytest granted report",
        proc_name="rpt.usp_pytest_unused",
    )
    db.add(role)
    db.add(report)
    db.flush()
    db.add(
        RoleReport(
            id=generate_id(),
            tenant_id=membership.tenant_id,
            role_id=role.id,
            report_id=report.id,
            can_view=True,
            can_export=False,
        )
    )
    db.flush()
    report.scope_type = "system"
    report.tenant_id = None
    with pytest.raises(DBAPIError) as exc_info:
        db.flush()
    assert "51009" in _orig(exc_info.value)


def test_soft_deleted_user_role_skips_integrity_trigger(
    tenant_integrity: Session, membership: TenantUser
) -> None:
    db = tenant_integrity
    role = _role(user_scope="tenant", tenant_id=membership.tenant_id, is_system=False)
    db.add(role)
    db.flush()
    assignment = UserRole(
        id=generate_id(),
        tenant_id=membership.tenant_id,
        user_id=membership.user_id,
        account_id=None,
        role_id=role.id,
        user_scope="tenant",
    )
    db.add(assignment)
    db.flush()
    assignment.is_deleted = True
    assignment.deleted_at = assignment.created_at
    assignment.deleted_by = membership.user_id
    db.flush()
