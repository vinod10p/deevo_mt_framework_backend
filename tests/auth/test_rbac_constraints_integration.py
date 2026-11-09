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

from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.auth.models.role_report import RoleReport
from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user import User
from mtf.auth.models.user_role import UserRole
from mtf.rpt.models.report_definition import ReportDefinition
from mtf.shared.database import SessionLocal
from mtf.shared.security import generate_id

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
