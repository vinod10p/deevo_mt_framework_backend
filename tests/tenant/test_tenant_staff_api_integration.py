"""Tenant-scoped staff API integration tests (requires live SQL Server).

Covers deevo_crm flow: subdomain lookup → login with tenant_id → /api/auth/me,
/api/tenant/me, and flat /api/tenant/users (owner/admin).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.shared.deps import CurrentUser, get_current_user
from tests.cleanup import soft_delete_users
from tests.staff_login import staff_headers
from tests.tenant.conftest import SEEDED_SYSTEM_USER_ID
from tests.tenant.rbac_fixtures import THIN_ADMIN_PERMISSIONS

pytestmark = pytest.mark.integration


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def _unique_subdomain(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"




@pytest.fixture(autouse=True)
def stub_system_user_for_staff_integration(
    clear_app_dependency_overrides: None,
) -> Generator[None, None, None]:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=SEEDED_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _create_tenant_with_owner(
    client: TestClient,
) -> dict[str, Any]:
    subdomain = _unique_subdomain("crm-staff")
    owner_email = _unique_email("crm-owner")
    owner_password = "OwnerSecret123!"

    create_tenant = client.post(
        "/api/tenant/",
        json={"name": "CRM Staff Integration Tenant", "subdomain": subdomain},
    )
    assert create_tenant.status_code == 201, create_tenant.text
    tenant_id = create_tenant.json()["id"]

    create_owner = client.post(
        f"/api/tenant/{tenant_id}/users",
        json={
            "email": owner_email,
            "password": owner_password,
            "role": "admin",
            "first_name": "CRM",
            "last_name": "Owner",
        },
    )
    assert create_owner.status_code == 201, create_owner.text
    owner_user_id = create_owner.json()["user_id"]

    return {
        "tenant_id": tenant_id,
        "subdomain": subdomain,
        "owner_email": owner_email,
        "owner_password": owner_password,
        "owner_user_id": owner_user_id,
    }


def test_tenant_crm_subdomain_login_and_me(client: TestClient) -> None:
    _skip_if_disabled()

    ctx = _create_tenant_with_owner(client)
    tenant_id = ctx["tenant_id"]
    owner_user_id = ctx["owner_user_id"]
    user_ids: list[str] = [owner_user_id]

    try:
        app.dependency_overrides.pop(get_current_user, None)

        lookup = client.get(
            "/api/tenant/by-subdomain",
            params={"subdomain": ctx["subdomain"].upper()},
        )
        assert lookup.status_code == 200, lookup.text
        assert lookup.json()["tenant_id"] == tenant_id

        headers = staff_headers(
            client,
            email=ctx["owner_email"],
            password=ctx["owner_password"],
            tenant_id=tenant_id,
        )

        me = client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200, me.text
        me_body = me.json()
        assert me_body["user_scope"] == "tenant"
        assert me_body["tenant_id"] == tenant_id
        assert me_body["role"] == "admin"
        assert me_body["email"] == ctx["owner_email"]
        # The admin template is thin: staff and role admin only, no product screens or
        # reports until roles grant them.
        assert set(me_body["permissions"]) == THIN_ADMIN_PERMISSIONS
        assert me_body["reports"] == []

        tenant_me = client.get("/api/tenant/me", headers=headers)
        assert tenant_me.status_code == 200, tenant_me.text
        assert tenant_me.json()["id"] == tenant_id
        assert tenant_me.json()["subdomain"] == ctx["subdomain"]

        staff = client.get("/api/tenant/users", headers=headers)
        assert staff.status_code == 200, staff.text
        assert any(row["user_id"] == owner_user_id for row in staff.json())

        one = client.get(f"/api/tenant/users/{owner_user_id}", headers=headers)
        assert one.status_code == 200, one.text
        assert one.json()["email"] == ctx["owner_email"]
        assert one.json()["role"] == "admin"

    finally:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id=SEEDED_SYSTEM_USER_ID,
            user_type="app_user",
            user_scope="system",
            tenant_id=None,
        )
        client.delete(f"/api/tenant/{tenant_id}")
        for uid in user_ids:
            soft_delete_users(uid)


def test_owner_creates_staff_via_flat_route(client: TestClient) -> None:
    _skip_if_disabled()

    ctx = _create_tenant_with_owner(client)
    tenant_id = ctx["tenant_id"]
    member_email = _unique_email("crm-member")
    user_ids: list[str] = [ctx["owner_user_id"]]

    try:
        app.dependency_overrides.pop(get_current_user, None)

        owner_headers = staff_headers(
            client,
            email=ctx["owner_email"],
            password=ctx["owner_password"],
            tenant_id=tenant_id,
        )

        create_member = client.post(
            "/api/tenant/users",
            headers=owner_headers,
            json={
                "email": member_email,
                "password": "MemberSecret123!",
                "role": "member",
                "first_name": "CRM",
                "last_name": "Member",
            },
        )
        assert create_member.status_code == 201, create_member.text
        created = create_member.json()
        member_user_id = created["user_id"]
        user_ids.append(member_user_id)

        assert created["tenant_id"] == tenant_id
        assert created["email"] == member_email
        assert created["role"] == "member"

        list_staff = client.get("/api/tenant/users", headers=owner_headers)
        assert list_staff.status_code == 200, list_staff.text
        ids = {row["user_id"] for row in list_staff.json()}
        assert member_user_id in ids

        member_headers = staff_headers(
            client,
            email=member_email,
            password="MemberSecret123!",
            tenant_id=tenant_id,
        )
        member_me = client.get("/api/auth/me", headers=member_headers)
        assert member_me.status_code == 200, member_me.text
        member_body = member_me.json()
        assert member_body["role"] == "member"
        # Members get no template: nothing until a role is assigned.
        assert member_body["permissions"] == []
        assert member_body["reports"] == []

    finally:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id=SEEDED_SYSTEM_USER_ID,
            user_type="app_user",
            user_scope="system",
            tenant_id=None,
        )
        client.delete(f"/api/tenant/{tenant_id}")
        for uid in user_ids:
            soft_delete_users(uid)


def test_member_cannot_create_staff_integration(client: TestClient) -> None:
    _skip_if_disabled()

    ctx = _create_tenant_with_owner(client)
    tenant_id = ctx["tenant_id"]
    member_email = _unique_email("crm-member-deny")
    user_ids: list[str] = [ctx["owner_user_id"]]

    try:
        app.dependency_overrides.pop(get_current_user, None)

        owner_headers = staff_headers(
            client,
            email=ctx["owner_email"],
            password=ctx["owner_password"],
            tenant_id=tenant_id,
        )
        create_member = client.post(
            "/api/tenant/users",
            headers=owner_headers,
            json={
                "email": member_email,
                "password": "MemberSecret123!",
                "role": "member",
            },
        )
        assert create_member.status_code == 201, create_member.text
        user_ids.append(create_member.json()["user_id"])

        member_headers = staff_headers(
            client,
            email=member_email,
            password="MemberSecret123!",
            tenant_id=tenant_id,
        )
        denied = client.post(
            "/api/tenant/users",
            headers=member_headers,
            json={
                "email": _unique_email("crm-other"),
                "password": "OtherSecret123!",
                "role": "member",
            },
        )
        assert denied.status_code == 403, denied.text
        assert denied.json()["detail"]["code"] == "AUTH_FORBIDDEN"

    finally:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id=SEEDED_SYSTEM_USER_ID,
            user_type="app_user",
            user_scope="system",
            tenant_id=None,
        )
        client.delete(f"/api/tenant/{tenant_id}")
        for uid in user_ids:
            soft_delete_users(uid)
