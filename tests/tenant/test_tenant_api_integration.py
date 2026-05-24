"""Tenant API integration tests (requires live SQL Server)."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.shared.deps import CurrentUser, get_current_user
from tests.tenant.conftest import SEEDED_SYSTEM_USER_ID

pytestmark = pytest.mark.integration


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def _unique_subdomain(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def stub_system_user_for_tenant_integration(clear_app_dependency_overrides: None) -> None:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=SEEDED_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_tenant_crud_flow(client: TestClient) -> None:
    _skip_if_disabled()
    subdomain = _unique_subdomain("tenant-api")

    # Create
    r = client.post(
        "/api/tenant/",
        json={"name": "Tenant API Integration Test", "subdomain": subdomain},
    )
    assert r.status_code == 201, r.text
    created = r.json()

    tenant_id = created["id"]
    row_version = created["row_version"]  # base64 string

    try:
        # List (should include created tenant)
        r = client.get("/api/tenant/?skip=0&limit=50")
        assert r.status_code == 200, r.text
        ids = {t["id"] for t in r.json()}
        assert tenant_id in ids

        # Get by id
        r = client.get(f"/api/tenant/{tenant_id}")
        assert r.status_code == 200, r.text

        # Patch
        r = client.patch(
            f"/api/tenant/{tenant_id}",
            json={"row_version": row_version, "name": "Tenant API Integration Test Updated"},
        )
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated["name"] == "Tenant API Integration Test Updated"

        new_row_version = updated["row_version"]
        assert new_row_version != row_version

        # Conflict (use stale row_version from before update)
        r = client.patch(
            f"/api/tenant/{tenant_id}",
            json={"row_version": row_version, "name": "Should Conflict"},
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "TENANT_TENANT_CONFLICT"

    finally:
        # Soft delete
        r = client.delete(f"/api/tenant/{tenant_id}")
        assert r.status_code == 204, r.text

        # Verify hidden from reads
        r = client.get(f"/api/tenant/{tenant_id}")
        assert r.status_code == 404, r.text


def test_create_duplicate_subdomain_409(client: TestClient) -> None:
    _skip_if_disabled()

    sub = _unique_subdomain("dup-sub")
    r1 = client.post("/api/tenant/", json={"name": "Dup Subdomain A", "subdomain": sub})
    assert r1.status_code == 201, r1.text
    tenant_id = r1.json()["id"]

    try:
        r2 = client.post("/api/tenant/", json={"name": "Dup Subdomain B", "subdomain": sub})
        assert r2.status_code == 409, r2.text
        detail = r2.json()["detail"]
        assert detail["code"] == "TENANT_SUBDOMAIN_CONFLICT"
        assert "subdomain" in detail["message"].lower()
    finally:
        client.delete(f"/api/tenant/{tenant_id}")


def test_get_tenant_by_subdomain_public_integration(client: TestClient) -> None:
    """Public lookup; no auth header required."""
    _skip_if_disabled()

    sub = _unique_subdomain("subdom-lookup")
    r_t = client.post("/api/tenant/", json={"name": "Subdomain Lookup Org", "subdomain": sub})
    assert r_t.status_code == 201, r_t.text
    tenant_id = r_t.json()["id"]

    try:
        r = client.get("/api/tenant/by-subdomain", params={"subdomain": sub.upper()})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tenant_id"] == tenant_id
        assert body["tenant_name"] == "Subdomain Lookup Org"
        assert body["subdomain"] == sub
        assert body["is_active"] is True
    finally:
        client.delete(f"/api/tenant/{tenant_id}")

