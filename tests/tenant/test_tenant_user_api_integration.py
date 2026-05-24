"""Tenant user nested API integration tests (requires live SQL Server)."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mtf.auth.models.user import User
from main import app
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser, get_current_user
from tests.tenant.conftest import SEEDED_SYSTEM_USER_ID

pytestmark = pytest.mark.integration


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def _unique_subdomain(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


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


@pytest.fixture(autouse=True)
def stub_system_user_for_tenant_user_integration(clear_app_dependency_overrides: None) -> None:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=SEEDED_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_tenant_user_master_detail_flow(client: TestClient) -> None:
    _skip_if_disabled()

    tenant_id: str | None = None
    user_id: str | None = None

    try:
        create_tenant = client.post(
            "/api/tenant/",
            json={
                "name": "Tenant User Integration Test",
                "subdomain": _unique_subdomain("tenant-user"),
            },
        )
        assert create_tenant.status_code == 201, create_tenant.text
        tenant = create_tenant.json()
        tenant_id = tenant["id"]

        raw_email = _unique_email("tenant-user")
        create_user = client.post(
            f"/api/tenant/{tenant_id}/users",
            json={
                "email": raw_email.upper(),
                "password": "Secret123!",
                "role": "member",
                "first_name": "Tenant",
                "last_name": "Member",
            },
        )
        assert create_user.status_code == 201, create_user.text
        created = create_user.json()
        user_id = created["user_id"]

        assert created["tenant_id"] == tenant_id
        assert created["email"] == raw_email.lower()
        assert created["user_scope"] == "tenant"
        assert created["role"] == "member"
        assert created["is_active"] is True
        assert created["is_deleted"] is False
        assert created["joined_at"] is not None

        list_users = client.get(f"/api/tenant/{tenant_id}/users", params={"skip": 0, "limit": 50})
        assert list_users.status_code == 200, list_users.text
        listed = list_users.json()
        assert any(row["user_id"] == user_id for row in listed)

        row_version = created["row_version"]
        update_user = client.patch(
            f"/api/tenant/{tenant_id}/users/{user_id}",
            json={
                "row_version": row_version,
                "role": "admin",
                "is_active": False,
            },
        )
        assert update_user.status_code == 200, update_user.text
        updated = update_user.json()
        assert updated["role"] == "admin"
        assert updated["is_active"] is False
        assert updated["row_version"] != row_version

        delete_membership = client.delete(f"/api/tenant/{tenant_id}/users/{user_id}")
        assert delete_membership.status_code == 204, delete_membership.text

        list_after_delete = client.get(f"/api/tenant/{tenant_id}/users", params={"skip": 0, "limit": 50})
        assert list_after_delete.status_code == 200, list_after_delete.text
        assert all(row["user_id"] != user_id for row in list_after_delete.json())

        get_user = client.get(f"/api/auth/users/{user_id}")
        assert get_user.status_code == 200, get_user.text
        user_body = get_user.json()
        assert user_body["id"] == user_id
        assert user_body["is_deleted"] is False
        assert user_body["user_scope"] == "tenant"

    finally:
        if tenant_id is not None:
            client.delete(f"/api/tenant/{tenant_id}")
        if user_id is not None:
            _cleanup_user(user_id)


def test_create_tenant_user_duplicate_email_409(client: TestClient) -> None:
    _skip_if_disabled()

    tenant_id: str | None = None
    user_id: str | None = None

    try:
        create_tenant = client.post(
            "/api/tenant/",
            json={
                "name": "Tenant User Duplicate Email Test",
                "subdomain": _unique_subdomain("tenant-user-dup"),
            },
        )
        assert create_tenant.status_code == 201, create_tenant.text
        tenant_id = create_tenant.json()["id"]

        email = _unique_email("tenant-user-dup")
        first_create = client.post(
            f"/api/tenant/{tenant_id}/users",
            json={
                "email": email,
                "password": "Secret123!",
                "role": "member",
            },
        )
        assert first_create.status_code == 201, first_create.text
        user_id = first_create.json()["user_id"]

        second_create = client.post(
            f"/api/tenant/{tenant_id}/users",
            json={
                "email": email,
                "password": "Secret123!",
                "role": "member",
            },
        )
        assert second_create.status_code == 409, second_create.text
        detail = second_create.json()["detail"]
        assert detail["code"] == "EMAIL_IN_USE"

    finally:
        if tenant_id is not None and user_id is not None:
            client.delete(f"/api/tenant/{tenant_id}/users/{user_id}")
        if tenant_id is not None:
            client.delete(f"/api/tenant/{tenant_id}")
        if user_id is not None:
            _cleanup_user(user_id)
