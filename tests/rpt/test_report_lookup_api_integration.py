"""Lookup endpoint integration tests — real HTTP → session-context connection → lookup proc.

Requires docs/rpt_seed_sample_report.sql. Uses a tenant that has accounts, so
tenant-scoped lookups (``usp_lookup_account``) return data.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from main import app
from mtf.rpt.models import ReportDefinition
from mtf.shared.database import SessionLocal
from mtf.shared.deps import get_current_user
from mtf.tenant.models import TenantAccount
from tests.rpt.conftest import OTHER_TENANT_ID, live_portal_user, live_tenant_staff, tenant_user

pytestmark = pytest.mark.integration

ROLE_URL = "/api/reports/tenant_user_list/lookups/role"
ACCOUNT_URL = "/api/reports/portal_user_list/lookups/account_id"


@pytest.fixture(scope="module")
def tenant_id() -> str:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    try:
        with SessionLocal() as db:
            seeded = db.scalars(
                select(ReportDefinition.id).where(
                    ReportDefinition.report_key == "tenant_user_list",
                    ReportDefinition.is_deleted == False,  # noqa: E712
                )
            ).first()
            found = db.scalars(
                select(TenantAccount.tenant_id).where(TenantAccount.is_deleted == False)  # noqa: E712
            ).first()
    except DBAPIError as exc:
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    if seeded is None or found is None:
        pytest.skip("rpt sample reports or tenant accounts not seeded")
    return found


@pytest.fixture
def client(tenant_id: str) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: live_tenant_staff(
        tenant_id=tenant_id
    )
    return TestClient(app)


def test_static_lookup_returns_all_options(client: TestClient) -> None:
    r = client.get(ROLE_URL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["value"] for i in body["items"]] == ["owner", "admin", "member", "viewer"]
    assert body["has_more"] is False


def test_lookup_limit_sets_has_more(client: TestClient) -> None:
    body = client.get(ROLE_URL, params={"limit": 1}).json()
    assert len(body["items"]) == 1
    assert body["has_more"] is True


def test_lookup_values_resolve_labels(client: TestClient) -> None:
    r = client.get(ROLE_URL, params=[("values", "viewer"), ("values", "admin")])
    assert r.status_code == 200
    assert r.json()["items"] == [
        {"value": "admin", "label": "Admin"},
        {"value": "viewer", "label": "Viewer"},
    ]


def test_lookup_search(client: TestClient) -> None:
    body = client.get(ROLE_URL, params={"q": "own"}).json()
    assert [i["value"] for i in body["items"]] == ["owner"]


def test_tenant_scoped_lookup_round_trip(client: TestClient) -> None:
    everything = client.get(ACCOUNT_URL).json()["items"]
    assert everything, "tenant has accounts, lookup should return them"
    first = everything[0]

    by_value = client.get(ACCOUNT_URL, params={"values": first["value"]}).json()["items"]
    assert by_value == [first]


def test_tenant_scoped_lookup_isolated_per_tenant() -> None:
    app.dependency_overrides[get_current_user] = lambda: tenant_user(OTHER_TENANT_ID)
    r = TestClient(app).get(ACCOUNT_URL)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_NOT_FOUND"


def test_portal_user_can_use_lookups(tenant_id: str) -> None:
    user = live_portal_user(tenant_id=tenant_id)
    app.dependency_overrides[get_current_user] = lambda: user
    assert TestClient(app).get(ROLE_URL).status_code == 200


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("/api/reports/tenant_user_list/lookups/joined_date", "REPORT_LOOKUP_NOT_FOUND"),
        ("/api/reports/tenant_user_list/lookups/is_active", "REPORT_LOOKUP_NOT_FOUND"),
        ("/api/reports/tenant_user_list/lookups/no_such_key", "REPORT_LOOKUP_NOT_FOUND"),
        ("/api/reports/no_such_report/lookups/role", "REPORT_NOT_FOUND"),
    ],
)
def test_lookup_not_found(client: TestClient, url: str, code: str) -> None:
    r = client.get(url)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == code
