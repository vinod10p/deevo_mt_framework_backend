"""FastAPI tests — report catalog routes (``/api/reports``, mocked service)."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.rpt.api.report import get_report_catalog_service
from mtf.rpt.schemas import (
    ReportColumnRead,
    ReportCriteriaRead,
    ReportDetailRead,
    ReportSummaryRead,
)
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.shared.exceptions import not_found
from tests.rpt.conftest import (
    TEST_TENANT_ID,
    portal_user,
    system_user,
    tenant_user,
)


def _detail() -> ReportDetailRead:
    return ReportDetailRead(
        report_key="tenant_account_list",
        display_name="Account List",
        description=None,
        scope_type="system",
        default_max_rows=20000,
        columns=[
            ReportColumnRead(
                column_name="name",
                display_name="Name",
                data_type="string",
                display_order=10,
                is_displayable=True,
                is_default_visible=True,
                is_sortable=True,
                is_groupable=False,
                is_filterable=True,
                is_aggregatable=False,
                default_aggregate_type=None,
                display_format=None,
                default_width=240,
            )
        ],
        criteria=[
            ReportCriteriaRead(
                criteria_key="account_type",
                display_name="Account Type",
                data_type="string",
                control_type="multiselect",
                has_lookup=True,
                default_value=None,
                is_required=False,
                display_order=10,
            )
        ],
    )


def _with_user(user: CurrentUser) -> MagicMock:
    svc = MagicMock()
    svc.list_reports.return_value = [
        ReportSummaryRead(
            report_key="tenant_account_list",
            display_name="Account List",
            description=None,
            scope_type="system",
        )
    ]
    svc.get_report.return_value = _detail()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_report_catalog_service] = lambda: svc
    return svc


def test_openapi_registers_report_paths() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/reports" in paths
    assert "/api/reports/{report_key}" in paths


def test_report_routes_require_bearer() -> None:
    client = TestClient(app)
    assert client.get("/api/reports").status_code in (401, 403)
    assert client.get("/api/reports/tenant_account_list").status_code in (401, 403)


def test_list_reports_tenant_scope_uses_jwt_tenant() -> None:
    svc = _with_user(tenant_user())
    r = TestClient(app).get("/api/reports", params={"skip": 5, "limit": 20})
    assert r.status_code == 200
    assert r.json()[0]["report_key"] == "tenant_account_list"
    svc.list_reports.assert_called_once_with(TEST_TENANT_ID, skip=5, limit=20)


def test_list_reports_portal_scope_allowed() -> None:
    svc = _with_user(portal_user())
    r = TestClient(app).get("/api/reports")
    assert r.status_code == 200
    svc.list_reports.assert_called_once_with(TEST_TENANT_ID, skip=0, limit=100)


def test_report_routes_forbidden_for_system_scope() -> None:
    svc = _with_user(system_user())
    client = TestClient(app)
    for path in ("/api/reports", "/api/reports/tenant_account_list"):
        r = client.get(path)
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "AUTH_FORBIDDEN"
    svc.list_reports.assert_not_called()
    svc.get_report.assert_not_called()


def test_report_routes_forbidden_without_tenant_in_token() -> None:
    svc = _with_user(tenant_user(tenant_id=None))
    r = TestClient(app).get("/api/reports")
    assert r.status_code == 403
    svc.list_reports.assert_not_called()


def test_get_report_returns_metadata_without_proc_names() -> None:
    svc = _with_user(tenant_user())
    r = TestClient(app).get("/api/reports/tenant_account_list")
    assert r.status_code == 200
    body = r.json()
    svc.get_report.assert_called_once_with(TEST_TENANT_ID, "tenant_account_list")
    assert body["columns"][0]["column_name"] == "name"
    assert body["criteria"][0]["has_lookup"] is True
    assert "proc_name" not in r.text
    assert "lookup_proc" not in r.text


def test_get_report_not_found() -> None:
    svc = _with_user(tenant_user())

    def _missing(*_: object) -> None:
        not_found("REPORT", "Report not found")

    svc.get_report.side_effect = _missing
    r = TestClient(app).get("/api/reports/does_not_exist")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_NOT_FOUND"
