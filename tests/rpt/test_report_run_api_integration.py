"""Run endpoint integration tests — real HTTP → criteria validation → report proc → JSON.

Requires docs/rpt_seed_sample_report.sql and a tenant with accounts and staff users.
"""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from main import app
from mtf.auth.models.tenant_user import TenantUser
from mtf.rpt.models import ReportDefinition
from mtf.shared.database import SessionLocal
from mtf.shared.deps import get_current_user
from mtf.tenant.models import TenantAccount
from tests.rpt.conftest import OTHER_TENANT_ID, portal_user, tenant_user

pytestmark = pytest.mark.integration

_ISO_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?")


@pytest.fixture(scope="module")
def tenant_id() -> str:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    try:
        with SessionLocal() as db:
            seeded = db.scalars(
                select(ReportDefinition.id).where(
                    ReportDefinition.report_key == "tenant_account_summary",
                    ReportDefinition.is_deleted == False,  # noqa: E712
                )
            ).first()
            account_tenants = set(
                db.scalars(
                    select(TenantAccount.tenant_id).where(TenantAccount.is_deleted == False)  # noqa: E712
                ).all()
            )
            staff_tenants = set(
                db.scalars(
                    select(TenantUser.tenant_id).where(TenantUser.is_deleted == False)  # noqa: E712
                ).all()
            )
    except DBAPIError as exc:
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    both = sorted(account_tenants & staff_tenants)
    if seeded is None or not both:
        pytest.skip("rpt sample reports, or a tenant with accounts and staff, not seeded")
    return both[0]


@pytest.fixture
def client(tenant_id: str) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: tenant_user(tenant_id)
    return TestClient(app)


def _columns(client: TestClient, report_key: str) -> dict[str, str]:
    meta = client.get(f"/api/reports/{report_key}").json()
    return {c["column_name"]: c["data_type"] for c in meta["columns"]}


@pytest.mark.parametrize(
    "report_key",
    [
        "tenant_account_list",
        "tenant_account_summary",
        "tenant_account_address_list",
        "tenant_user_list",
        "portal_user_list",
    ],
)
def test_every_sample_report_runs_with_json_types_matching_metadata(
    client: TestClient, report_key: str
) -> None:
    columns = _columns(client, report_key)
    r = client.post(f"/api/reports/{report_key}/run", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_key"] == report_key
    assert body["row_count"] == len(body["rows"])
    assert body["truncated"] is False

    for row in body["rows"]:
        assert set(row) == set(columns)
        for name, value in row.items():
            if value is None:
                continue
            data_type = columns[name]
            if data_type == "int":
                assert isinstance(value, int) and not isinstance(value, bool), name
            elif data_type == "decimal":
                assert isinstance(value, int | float) and not isinstance(value, bool), name
            elif data_type == "bool":
                assert isinstance(value, bool), name
            elif data_type == "datetime":
                assert _ISO_DATETIME.fullmatch(value), (name, value)
            elif data_type == "date":
                assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), (name, value)
            else:
                assert isinstance(value, str), name


def test_filters_apply(client: TestClient) -> None:
    criteria = {"role": ["owner"], "is_active": True, "joined_date": {"to": "2100-12-31"}}
    body = client.post(
        "/api/reports/tenant_user_list/run", json={"criteria": criteria}
    ).json()
    assert all(row["role"] == "owner" and row["is_active"] is True for row in body["rows"])

    none = client.post(
        "/api/reports/tenant_account_list/run",
        json={"criteria": {"created_date": {"from": "2100-01-01"}}},
    ).json()
    assert none["rows"] == [] and none["row_count"] == 0


def test_summary_counts_add_up(client: TestClient) -> None:
    summary = client.post("/api/reports/tenant_account_summary/run", json={}).json()["rows"]
    detail = client.post("/api/reports/tenant_account_list/run", json={}).json()["rows"]
    assert sum(row["account_count"] for row in summary) == len(detail)
    for row in summary:
        assert row["active_count"] + row["inactive_count"] == row["account_count"]


def test_max_rows_truncates(client: TestClient) -> None:
    full = client.post("/api/reports/tenant_user_list/run", json={}).json()
    if full["row_count"] < 2:
        pytest.skip("need at least two staff users")
    one = client.post("/api/reports/tenant_user_list/run", json={"max_rows": 1}).json()
    assert one["row_count"] == 1
    assert one["truncated"] is True
    assert one["rows"][0] == full["rows"][0]


def test_invalid_criteria_returns_fields(client: TestClient) -> None:
    criteria = {
        "status": ["active"],
        "created_date": {"from": "2026-12-31", "to": "2026-01-01"},
        "tenant_id": "x",
    }
    r = client.post("/api/reports/tenant_account_list/run", json={"criteria": criteria})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "REPORT_CRITERIA_INVALID"
    assert set(detail["fields"]) == {"status", "created_date", "tenant_id"}


def test_unknown_report_404(client: TestClient) -> None:
    r = client.post("/api/reports/no_such_report/run", json={})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_NOT_FOUND"


def test_other_tenant_gets_no_rows(client: TestClient) -> None:
    mine = client.post("/api/reports/tenant_account_list/run", json={}).json()
    assert mine["row_count"] > 0
    app.dependency_overrides[get_current_user] = lambda: tenant_user(OTHER_TENANT_ID)
    theirs = client.post("/api/reports/tenant_account_list/run", json={}).json()
    assert theirs["rows"] == []


def test_portal_user_can_run(tenant_id: str) -> None:
    user = portal_user()
    app.dependency_overrides[get_current_user] = lambda: user
    r = TestClient(app).post("/api/reports/tenant_user_list/run", json={})
    assert r.status_code == 200
