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
from mtf.auth.models.user_role import UserRole
from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.tenant.business_units import root_unit_id
from mtf.tenant.models.tenant_setting import TenantSetting
from mtf.tenant.services.rbac_screens import RBAC_SCREENS_KEY, RBAC_SCREENS_ON
from tests.cleanup import soft_delete_tenant_roles, soft_delete_users
from tests.tenant.conftest import SEEDED_SYSTEM_USER_ID
from tests.tenant.rbac_fixtures import THIN_ADMIN_PERMISSIONS

pytestmark = pytest.mark.integration


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"




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
            flag = db.scalars(
                select(TenantSetting).where(
                    TenantSetting.tenant_id == tenant_id,
                    TenantSetting.key == RBAC_SCREENS_KEY,
                    TenantSetting.is_deleted == False,  # noqa: E712
                )
            ).first()
        assert default_count is not None
        if default_count == 0:
            pytest.skip("no default_role_report rows; apply sql/auth_rbac_seed_v3.sql")
        assert copied == default_count
        assert flag is not None
        assert flag.value == RBAC_SCREENS_ON
    finally:
        if tenant_id is not None:
            client.delete(f"/api/tenant/{tenant_id}")


def _add_staff(client: TestClient, tenant_id: str, *, role: str) -> dict:
    """Create a staff member of ``tenant_id`` through the API and return the response body."""
    response = client.post(
        f"/api/tenant/{tenant_id}/users",
        json={
            "email": f"{_unique(f'rbac-{role}')}@example.com",
            "password": "Secret123!",
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_tenant_membership_dual_write_and_resolver(
    client: TestClient,
    rbac_ready: None,
) -> None:
    tenant_id: str | None = None
    user_ids: list[str] = []
    try:
        created = client.post(
            "/api/tenant/",
            json={"name": "RBAC Dual-Write Tenant", "subdomain": _unique("rbac-dual")},
        )
        assert created.status_code == 201, created.text
        tenant_id = created.json()["id"]
        # A second admin, so the member below can be promoted, demoted and removed.
        user_ids.append(_add_staff(client, tenant_id, role="admin")["user_id"])

        body = _add_staff(client, tenant_id, role="member")
        user_id = body["user_id"]
        user_ids.append(user_id)
        # Members get no template: access comes only from roles assigned to them.
        assert _live_role_code(tenant_id, user_id) is None
        assert _permission_codes(tenant_id, user_id) == frozenset()

        updated = client.patch(
            f"/api/tenant/{tenant_id}/users/{user_id}",
            json={"row_version": body["row_version"], "role": "admin"},
        )
        assert updated.status_code == 200, updated.text
        assert _live_role_code(tenant_id, user_id) == "tenant_admin"
        assert _permission_codes(tenant_id, user_id) == THIN_ADMIN_PERMISSIONS

        demoted = client.patch(
            f"/api/tenant/{tenant_id}/users/{user_id}",
            json={"row_version": updated.json()["row_version"], "role": "member"},
        )
        assert demoted.status_code == 200, demoted.text
        assert _live_role_code(tenant_id, user_id) is None

        deleted = client.delete(f"/api/tenant/{tenant_id}/users/{user_id}")
        assert deleted.status_code == 204, deleted.text
        assert _live_role_code(tenant_id, user_id) is None
    finally:
        if tenant_id is not None:
            client.delete(f"/api/tenant/{tenant_id}")
        soft_delete_users(*user_ids)


def _permission_codes(tenant_id: str, user_id: str) -> frozenset[str]:
    actor = CurrentUser(
        user_id=user_id, user_type="app_user", user_scope="tenant", tenant_id=tenant_id
    )
    with SessionLocal() as db:
        return PermissionResolver(db).permission_codes(actor)


def _live_role_codes(tenant_id: str, user_id: str) -> set[str]:
    with SessionLocal() as db:
        return set(
            db.scalars(
                select(Role.code)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(
                    UserRole.tenant_id == tenant_id,
                    UserRole.user_id == user_id,
                    UserRole.account_id.is_(None),
                    UserRole.is_deleted == False,  # noqa: E712
                )
            ).all()
        )


def test_membership_update_keeps_custom_role(
    client: TestClient,
    rbac_ready: None,
) -> None:
    tenant_id: str | None = None
    user_ids: list[str] = []
    try:
        created = client.post(
            "/api/tenant/",
            json={"name": "RBAC Custom Keep", "subdomain": _unique("rbac-keep")},
        )
        assert created.status_code == 201, created.text
        tenant_id = created.json()["id"]
        user_ids.append(_add_staff(client, tenant_id, role="admin")["user_id"])

        member = _add_staff(client, tenant_id, role="member")
        user_id = member["user_id"]
        user_ids.append(user_id)

        with SessionLocal() as db:
            place = {"tenant_id": tenant_id, "business_unit_id": root_unit_id(db, tenant_id)}
            role = Role.new(
                by=SEEDED_SYSTEM_USER_ID,
                **place,
                code="support_lead",
                name="Support Lead",
                user_scope="tenant",
                is_system=False,
            )
            db.add(role)
            db.flush()
            db.add(
                UserRole.new(
                    by=SEEDED_SYSTEM_USER_ID,
                    **place,
                    user_id=user_id,
                    role_id=role.id,
                    user_scope="tenant",
                )
            )
            db.commit()
        assert _live_role_codes(tenant_id, user_id) == {"support_lead"}

        renamed = client.patch(
            f"/api/tenant/{tenant_id}/users/{user_id}",
            json={"row_version": member["row_version"], "first_name": "Renamed"},
        )
        assert renamed.status_code == 200, renamed.text
        assert _live_role_codes(tenant_id, user_id) == {"support_lead"}

        promoted = client.patch(
            f"/api/tenant/{tenant_id}/users/{user_id}",
            json={"row_version": renamed.json()["row_version"], "role": "admin"},
        )
        assert promoted.status_code == 200, promoted.text
        assert _live_role_codes(tenant_id, user_id) == {"tenant_admin", "support_lead"}

        demoted = client.patch(
            f"/api/tenant/{tenant_id}/users/{user_id}",
            json={"row_version": promoted.json()["row_version"], "role": "member"},
        )
        assert demoted.status_code == 200, demoted.text
        assert _live_role_codes(tenant_id, user_id) == {"support_lead"}

        deleted = client.delete(f"/api/tenant/{tenant_id}/users/{user_id}")
        assert deleted.status_code == 204, deleted.text
        assert _live_role_codes(tenant_id, user_id) == set()
    finally:
        if tenant_id is not None:
            soft_delete_tenant_roles(tenant_id)
            client.delete(f"/api/tenant/{tenant_id}")
        soft_delete_users(*user_ids)


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
            soft_delete_users(uid)
