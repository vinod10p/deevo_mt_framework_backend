"""Report catalog integration tests (requires live SQL Server with rpt schema + sample seed).

Apply ``docs/rpt_schema_v5.sql`` and ``docs/rpt_seed_sample_report.sql`` in SSMS first;
tests skip when the seeded ``tenant_account_list`` system report is not present.
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
from tests.rpt.conftest import live_portal_user, live_tenant_staff

pytestmark = pytest.mark.integration

_SEEDED_KEY = "tenant_account_list"


@pytest.fixture(autouse=True)
def require_seeded_report() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    try:
        with SessionLocal() as db:
            found = db.scalars(
                select(ReportDefinition.id).where(
                    ReportDefinition.report_key == _SEEDED_KEY,
                    ReportDefinition.scope_type == "system",
                    ReportDefinition.is_deleted == False,  # noqa: E712
                )
            ).first()
    except DBAPIError as exc:
        pytest.skip(f"rpt schema not available: {exc.__class__.__name__}")
    if found is None:
        pytest.skip("rpt sample report not seeded (docs/rpt_seed_sample_report.sql)")


def test_list_reports_includes_seeded_system_report() -> None:
    app.dependency_overrides[get_current_user] = lambda: live_tenant_staff()
    r = TestClient(app).get("/api/reports")
    assert r.status_code == 200, r.text
    assert _SEEDED_KEY in [item["report_key"] for item in r.json()]


def test_get_seeded_report_metadata() -> None:
    app.dependency_overrides[get_current_user] = lambda: live_tenant_staff()
    r = TestClient(app).get(f"/api/reports/{_SEEDED_KEY}")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["scope_type"] == "system"
    orders = [c["display_order"] for c in body["columns"]]
    assert orders == sorted(orders)
    assert {"account_code", "name", "account_type", "status"} <= {
        c["column_name"] for c in body["columns"]
    }
    criteria = {c["criteria_key"]: c for c in body["criteria"]}
    assert criteria["account_type"]["has_lookup"] is True
    assert criteria["created_date"]["has_lookup"] is False
    assert "proc_name" not in r.text
    assert "lookup_proc" not in r.text
    assert body["actions"] == []


def test_system_report_visible_to_any_tenant_and_portal() -> None:
    client = TestClient(app)
    for user in (live_tenant_staff(), live_portal_user()):
        app.dependency_overrides[get_current_user] = lambda u=user: u
        r = client.get(f"/api/reports/{_SEEDED_KEY}")
        assert r.status_code == 200, r.text


def test_unknown_report_key_returns_404() -> None:
    app.dependency_overrides[get_current_user] = lambda: live_tenant_staff()
    r = TestClient(app).get("/api/reports/no_such_report_key")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_NOT_FOUND"
