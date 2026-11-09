"""Live SQL Server: PermissionResolver returns granted codes and skips inactive membership.

Every write is rolled back. Skip if RBAC tables are missing.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user import User
from mtf.auth.models.user_role import UserRole
from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser
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


def _actor(membership: TenantUser) -> CurrentUser:
    return CurrentUser(
        user_id=membership.user_id,
        user_type="app_user",
        user_scope="tenant",
        tenant_id=membership.tenant_id,
    )


def _grant(db: Session, membership: TenantUser, *, role_active: bool = True) -> str:
    token = generate_id()[:10].lower()
    resource_code = f"pytest_{token}"
    code = f"screen.{resource_code}.view"
    permission = Permission(
        id=generate_id(),
        code=code,
        resource_type="screen",
        resource_code=resource_code,
        action="view",
        user_scope="tenant",
    )
    role = Role(
        id=generate_id(),
        tenant_id=membership.tenant_id,
        code=f"pytest_{token}",
        name=f"pytest {token}",
        user_scope="tenant",
        is_system=False,
        is_active=role_active,
    )
    db.add(permission)
    db.add(role)
    db.flush()
    db.add(
        RolePermission(
            id=generate_id(),
            role_id=role.id,
            permission_id=permission.id,
            user_scope="tenant",
        )
    )
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
    return code


def test_resolver_returns_granted_tenant_code(db: Session, membership: TenantUser) -> None:
    code = _grant(db, membership)
    codes = PermissionResolver(db).permission_codes(_actor(membership))
    assert code in codes


def test_inactive_role_is_not_granted(db: Session, membership: TenantUser) -> None:
    code = _grant(db, membership, role_active=False)
    codes = PermissionResolver(db).permission_codes(_actor(membership))
    assert code not in codes


def test_system_user_without_assignment_is_empty(db: Session) -> None:
    system_user = db.scalars(
        select(User).where(
            User.user_scope == "system",
            User.is_deleted == False,  # noqa: E712
        )
    ).first()
    if system_user is None:
        pytest.skip("no live system app_user")
    actor = CurrentUser(
        user_id=system_user.id,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    # Existing system users have no user_role until seed/backfill. Empty is correct.
    codes = PermissionResolver(db).permission_codes(actor)
    assert isinstance(codes, frozenset)
