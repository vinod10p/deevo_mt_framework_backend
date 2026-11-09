"""Live SQL Server: create_tenant copies defaults; membership dual-writes user_role."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from main import app
from mtf.auth.models.default_role_report import DefaultRoleReport
from mtf.auth.models.role import Role
from mtf.auth.models.role_report import RoleReport
from mtf.auth.models.user import User
from mtf.auth.models.user_role import UserRole
from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser, get_current_user
from tests.tenant.conftest import SEEDED_SYSTEM_USER_ID

pytestmark = pytest.mark.integration


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _cleanup_user(user_id: str) -> None:
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.id == user_id)).first()
        if user is None:
            return
        user.is_active = False
        user.is_deleted = True
        user.updated_by = SEEDED_SYSTEM_USER_ID
        user.deleted_by = SEEDED_SYSTEM_USER_ID
        db.add(user)
        db.commit()


def _live_role_code(tenant_id: str, user_id: str, *, account_id: str | None = None) -> str | None:
    with SessionLocal() as db:
        stmt = (
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.tenant_id == tenant_id,
                UserRole.user_id == user_id,
                UserRole.is_deleted == False,  # noqa: E712
            )
        )
        if account_id is None:
            stmt = stmt.where(UserRole.account_id.is_(None))
        else:
            stmt = stmt.where(UserRole.account_id == account_id)
        return db.scalars(stmt).first()


@pytest.fixture(autouse=True)
def stub_system_user(clear_app_dependency_overrides: None) -> None:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=SEEDED_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def rbac_ready() -> None:
    _skip_if_disabled()
    try:
        with SessionLocal() as db:
            db.execute(select(1))
            present = db.execute(text("SELECT OBJECT_ID('auth.role', 'U')")).scalar()
            if present is None:
                pytest.skip("auth.role is not present; apply sql/auth_rbac_schema_v3.sql")
            admin = db.scalars(
                select(Role).where(
                    Role.tenant_id.is_(None),
                    Role.code == "tenant_admin",
                    Role.is_deleted == False,  # noqa: E712
                )
            ).first()
            if admin is None:
                pytest.skip("platform roles missing; apply sql/auth_rbac_seed_v3.sql")
    except DBAPIError as exc:
        pytest.skip(f"database not available: {exc.__class__.__name__}")


def test_create_tenant_copies_default_role_reports(
    client: TestClient,
    rbac_ready: None,
) -> None:
    tenant_id: str | None = None
    try:
        created = client.post(
            "/api/tenant/",
            json={
                "name": "RBAC Onboarding Tenant",
                "subdomain": _unique("rbac-onboard"),
            },
        )
        assert created.status_code == 201, created.text
        tenant_id = created.json()["id"]

        with SessionLocal() as db:
            default_count = db.scalar(
                select(func.count()).select_from(DefaultRoleReport).where(
                    DefaultRoleReport.is_active == True,  # noqa: E712
                    DefaultRoleReport.is_deleted == False,  # noqa: E712
                )
            )
            copied = db.scalar(
                select(func.count()).select_from(RoleReport).where(
                    RoleReport.tenant_id == tenant_id,
                    RoleReport.is_deleted == False,  # noqa: E712
                )
            )
        assert default_count is not None
        if default_count == 0:
            pytest.skip("no default_role_report rows; apply sql/auth_rbac_seed_v3.sql")
        assert copied == default_count
    finally:
        if tenant_id is not None:
            client.delete(f"/api/tenant/{tenant_id}")


def test_tenant_membership_dual_write_and_resolver(
    client: TestClient,
    rbac_ready: None,
) -> None:
    tenant_id: str | None = None
    user_id: str | None = None
    try:
        created = client.post(
            "/api/tenant/",
            json={
                "name": "RBAC Dual-Write Tenant",
                "subdomain": _unique("rbac-dual"),
            },
        )
        assert created.status_code == 201, created.text
        tenant_id = created.json()["id"]

        member = client.post(
            f"/api/tenant/{tenant_id}/users",
            json={
                "email": f"{_unique('rbac-member')}@example.com",
                "password": "Secret123!",
                "role": "member",
                "first_name": "Rbac",
                "last_name": "Member",
            },
        )
        assert member.status_code == 201, member.text
        body = member.json()
        user_id = body["user_id"]
        assert _live_role_code(tenant_id, user_id) == "tenant_member"

        with SessionLocal() as db:
            actor = CurrentUser(
                user_id=user_id,
                user_type="app_user",
                user_scope="tenant",
                tenant_id=tenant_id,
            )
            codes = PermissionResolver(db).permission_codes(actor)
        assert "screen.lead.view" in codes
        assert "api.auth.role.update" not in codes

        updated = client.patch(
            f"/api/tenant/{tenant_id}/users/{user_id}",
            json={"row_version": body["row_version"], "role": "admin"},
        )
        assert updated.status_code == 200, updated.text
        assert _live_role_code(tenant_id, user_id) == "tenant_admin"

        with SessionLocal() as db:
            actor = CurrentUser(
                user_id=user_id,
                user_type="app_user",
                user_scope="tenant",
                tenant_id=tenant_id,
            )
            codes = PermissionResolver(db).permission_codes(actor)
        assert "api.auth.role.update" in codes

        deleted = client.delete(f"/api/tenant/{tenant_id}/users/{user_id}")
        assert deleted.status_code == 204, deleted.text
        assert _live_role_code(tenant_id, user_id) is None
    finally:
        if tenant_id is not None:
            client.delete(f"/api/tenant/{tenant_id}")
        if user_id is not None:
            _cleanup_user(user_id)


def test_account_membership_dual_write(
    client: TestClient,
    rbac_ready: None,
) -> None:
    tenant_id: str | None = None
    user_ids: list[str] = []
    try:
        created = client.post(
            "/api/tenant/",
            json={
                "name": "RBAC Portal Dual-Write",
                "subdomain": _unique("rbac-portal"),
            },
        )
        assert created.status_code == 201, created.text
        tenant_id = created.json()["id"]

        account = client.post(
            f"/api/tenant/{tenant_id}/accounts",
            json={
                "account_code": uuid.uuid4().hex[:12],
                "account_type": "customer",
                "name": "RBAC Portal Account",
            },
        )
        assert account.status_code == 201, account.text
        account_id = account.json()["id"]

        portal = client.post(
            f"/api/tenant/{tenant_id}/accounts/{account_id}/users",
            json={
                "email": f"{_unique('rbac-portal')}@example.com",
                "password": "Secret123!",
                "role": "member",
            },
        )
        assert portal.status_code == 201, portal.text
        user_id = portal.json()["user_id"]
        user_ids.append(user_id)
        assert _live_role_code(tenant_id, user_id, account_id=account_id) == (
            "account_member"
        )

        patched = client.patch(
            f"/api/tenant/{tenant_id}/accounts/{account_id}/users/{user_id}",
            json={"row_version": portal.json()["row_version"], "role": "admin"},
        )
        assert patched.status_code == 200, patched.text
        assert _live_role_code(tenant_id, user_id, account_id=account_id) == (
            "account_admin"
        )

        other = client.post(
            f"/api/tenant/{tenant_id}/accounts/{account_id}/users",
            json={
                "email": f"{_unique('rbac-portal2')}@example.com",
                "password": "Secret123!",
                "role": "member",
            },
        )
        assert other.status_code == 201, other.text
        other_id = other.json()["user_id"]
        user_ids.append(other_id)
        deleted = client.delete(
            f"/api/tenant/{tenant_id}/accounts/{account_id}/users/{other_id}"
        )
        assert deleted.status_code == 204, deleted.text
        assert _live_role_code(tenant_id, other_id, account_id=account_id) is None
        assert _live_role_code(tenant_id, user_id, account_id=account_id) == (
            "account_admin"
        )
    finally:
        if tenant_id is not None:
            client.delete(f"/api/tenant/{tenant_id}")
        for uid in user_ids:
            _cleanup_user(uid)
