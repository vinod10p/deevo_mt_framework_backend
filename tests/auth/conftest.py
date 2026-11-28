"""Auth test fixtures — system login for integration tests."""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator, Iterator

import pytest
from fastapi.testclient import TestClient

from tests.cleanup import soft_delete_tenants, soft_delete_users
from tests.staff_login import PASSWORD


@pytest.fixture
def system_auth_headers(client: TestClient) -> dict[str, str]:
    """Bearer token for bootstrap system user (integration tests only)."""
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")

    email = os.environ.get("DEEVO_TEST_SYSTEM_EMAIL", "vinod@deevolight.com")
    password = os.environ.get("DEEVO_TEST_SYSTEM_PASSWORD", "vinod123")
    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "created_from": "web"},
    )
    if r.status_code != 200:
        pytest.skip(f"system login failed: {r.status_code} {r.text}")
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def clear_app_dependency_overrides() -> Generator[None, None, None]:
    from main import app

    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def staff(client: TestClient, system_auth_headers: dict[str, str]) -> Iterator[dict]:
    """A fresh tenant with one admin staff user."""
    suffix = uuid.uuid4().hex[:12]
    create = client.post(
        "/api/tenant/",
        json={"name": "Session Revocation", "subdomain": f"sess-rev-{suffix}"},
        headers=system_auth_headers,
    )
    assert create.status_code == 201, create.text
    tenant_id = create.json()["id"]
    email = f"sess-rev-{suffix}@example.com"
    user = client.post(
        f"/api/tenant/{tenant_id}/users",
        json={"email": email, "password": PASSWORD, "role": "admin", "first_name": "S"},
        headers=system_auth_headers,
    )
    assert user.status_code == 201, user.text
    user_id = user.json()["user_id"]
    try:
        yield {"tenant_id": tenant_id, "email": email, "user_id": user_id}
    finally:
        soft_delete_users(user_id)
        soft_delete_tenants(tenant_id)
