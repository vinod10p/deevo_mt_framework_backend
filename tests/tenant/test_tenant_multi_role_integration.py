"""Live SQL Server: one tenant user can hold several roles; grants are a union."""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from main import app
from mtf.auth.models.role import Role
from mtf.auth.models.user import User
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser, get_current_user
from tests.tenant.conftest import SEEDED_SYSTEM_USER_ID
from tests.tenant.rbac_fixtures import assign_role, create_member, custom_role

pytestmark = pytest.mark.integration


def _system_user() -> CurrentUser:
    return CurrentUser(
        user_id=SEEDED_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )


@pytest.fixture(autouse=True)
def stub_system_user(clear_app_dependency_overrides: None) -> Generator[None, None, None]:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    app.dependency_overrides[get_current_user] = _system_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _login(client: TestClient, *, email: str, password: str, tenant_id: str) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
            "tenant_id": tenant_id,
            "created_from": "web",
        },
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _me_permissions(client: TestClient, headers: dict[str, str]) -> set[str]:
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return set(r.json()["permissions"])


def _role_codes(client: TestClient, headers: dict[str, str], user_id: str) -> dict[str, str]:
    r = client.get(f"/api/tenant/users/{user_id}/roles", headers=headers)
    assert r.status_code == 200, r.text
    role_ids = [row["role_id"] for row in r.json()]
    if not role_ids:
        return {}
    with SessionLocal() as db:
        rows = db.scalars(select(Role).where(Role.id.in_(role_ids))).all()
    return {row.id: row.code for row in rows}


def _cleanup(client: TestClient, tenant_id: str, user_ids: list[str]) -> None:
    app.dependency_overrides[get_current_user] = _system_user
    client.delete(f"/api/tenant/{tenant_id}")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as db:
        for user in db.scalars(select(User).where(User.id.in_(user_ids))).all():
            user.is_active = False
            user.is_deleted = True
            user.updated_by = SEEDED_SYSTEM_USER_ID
            user.deleted_by = SEEDED_SYSTEM_USER_ID
            db.add(user)
        for role in db.scalars(
            select(Role).where(Role.tenant_id == tenant_id, Role.is_deleted == False)  # noqa: E712
        ).all():
            role.is_deleted = True
            role.deleted_at = now
            role.deleted_by = SEEDED_SYSTEM_USER_ID
            role.updated_by = SEEDED_SYSTEM_USER_ID
            db.add(role)
        db.commit()


def _setup(client: TestClient) -> dict[str, Any]:
    owner_email = f"{_unique('multi-admin')}@example.com"
    tenant = client.post(
        "/api/tenant/",
        json={"name": "Multi Role Tenant", "subdomain": _unique("multi-role")},
    )
    assert tenant.status_code == 201, tenant.text
    tenant_id = tenant.json()["id"]
    owner = client.post(
        f"/api/tenant/{tenant_id}/users",
        json={
            "email": owner_email,
            "password": "OwnerSecret123!",
            "role": "admin",
            "first_name": "Multi",
            "last_name": "Admin",
        },
    )
    assert owner.status_code == 201, owner.text
    return {
        "tenant_id": tenant_id,
        "owner_email": owner_email,
        "owner_user_id": owner.json()["user_id"],
    }


def test_user_holds_multiple_roles_with_union_of_grants(client: TestClient) -> None:
    ctx = _setup(client)
    tenant_id = ctx["tenant_id"]
    user_ids = [ctx["owner_user_id"]]
    try:
        app.dependency_overrides.pop(get_current_user, None)
        admin = _login(
            client, email=ctx["owner_email"], password="OwnerSecret123!", tenant_id=tenant_id
        )
        member_id, member_email = create_member(client, admin)
        user_ids.append(member_id)
        member = _login(
            client, email=member_email, password="MemberSecret123!", tenant_id=tenant_id
        )
        assert _role_codes(client, admin, member_id) == {}
        assert _me_permissions(client, member) == set()

        first = custom_role(client, admin, "one", ["screen.lead.view"])
        second = custom_role(client, admin, "two", ["screen.note.view"])
        assign_role(client, admin, member_id, first["id"])
        assign_role(client, admin, member_id, second["id"])
        assert set(_role_codes(client, admin, member_id).values()) == {
            first["code"],
            second["code"],
        }
        assert _me_permissions(client, member) == {"screen.lead.view", "screen.note.view"}

        duplicate = client.post(
            f"/api/tenant/users/{member_id}/roles",
            headers=admin,
            json={"role_id": first["id"]},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "AUTH_USER_ROLE_CONFLICT"

        staff = client.get(f"/api/tenant/users/{member_id}", headers=admin).json()
        promoted = client.patch(
            f"/api/tenant/users/{member_id}",
            headers=admin,
            json={"row_version": staff["row_version"], "role": "admin"},
        )
        assert promoted.status_code == 200, promoted.text
        held = set(_role_codes(client, admin, member_id).values())
        assert held == {"tenant_admin", first["code"], second["code"]}
        assert "api.auth.role.update" in _me_permissions(client, member)
    finally:
        _cleanup(client, tenant_id, user_ids)
