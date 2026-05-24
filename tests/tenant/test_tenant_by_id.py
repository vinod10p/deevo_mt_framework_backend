"""Public ``GET /api/tenant/by-id`` — deevo_account tenant lookup."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.tenant.api.tenant import get_tenant_service

from tests.tenant.conftest import TEST_TENANT_ID, minimal_tenant


def test_get_tenant_by_id_public_200() -> None:
    svc = MagicMock()
    row = minimal_tenant()
    svc.get_tenant.return_value = row
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/tenant/by-id", params={"tenant_id": TEST_TENANT_ID})
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == TEST_TENANT_ID
    assert body["tenant_name"] == row.name
    svc.get_tenant.assert_called_once_with(TEST_TENANT_ID)


def test_get_tenant_by_id_404() -> None:
    svc = MagicMock()
    svc.get_tenant.return_value = None
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/tenant/by-id", params={"tenant_id": TEST_TENANT_ID})
    assert r.status_code == 404


def test_get_tenant_by_id_inactive_403() -> None:
    svc = MagicMock()
    svc.get_tenant.return_value = minimal_tenant(is_active=False)
    app.dependency_overrides[get_tenant_service] = lambda: svc

    client = TestClient(app)
    r = client.get("/api/tenant/by-id", params={"tenant_id": TEST_TENANT_ID})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "TENANT_INACTIVE"
