"""FastAPI tests — ``GET /api/reports/{report_key}/lookups/{criteria_key}`` (mocked service)."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.rpt.api.deps import get_report_connection
from mtf.rpt.api.report import get_report_lookup_service
from mtf.rpt.schemas import ReportLookupOption, ReportLookupRead
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.shared.exceptions import not_found
from tests.rpt.conftest import TEST_TENANT_ID, portal_user, system_user, tenant_user

URL = "/api/reports/tenant_account_list/lookups/account_type"
CONN = object()


def _with_user(user: CurrentUser) -> MagicMock:
    svc = MagicMock()
    svc.get_options.return_value = ReportLookupRead(
        items=[ReportLookupOption(value="customer", label="Customer")], has_more=False
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_report_lookup_service] = lambda: svc
    app.dependency_overrides[get_report_connection] = lambda: CONN
    return svc


def test_openapi_registers_lookup_path() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/reports/{report_key}/lookups/{criteria_key}" in paths


def test_lookup_requires_bearer() -> None:
    assert TestClient(app).get(URL).status_code in (401, 403)


def test_lookup_returns_items_and_has_more() -> None:
    svc = _with_user(tenant_user())
    r = TestClient(app).get(URL)
    assert r.status_code == 200
    assert r.json() == {"items": [{"value": "customer", "label": "Customer"}], "has_more": False}
    svc.get_options.assert_called_once_with(
        CONN, TEST_TENANT_ID, "tenant_account_list", "account_type",
        q=None, values=None, limit=None,
    )


def test_lookup_passes_query_params_with_repeated_values() -> None:
    svc = _with_user(portal_user())
    r = TestClient(app).get(
        URL, params=[("q", "cus"), ("values", "C001"), ("values", "C002"), ("limit", "25")]
    )
    assert r.status_code == 200
    svc.get_options.assert_called_once_with(
        CONN, TEST_TENANT_ID, "tenant_account_list", "account_type",
        q="cus", values=["C001", "C002"], limit=25,
    )


def test_lookup_rejects_long_search_text() -> None:
    svc = _with_user(tenant_user())
    r = TestClient(app).get(URL, params={"q": "x" * 201})
    assert r.status_code == 422
    svc.get_options.assert_not_called()


def test_lookup_forbidden_for_system_scope_before_connecting() -> None:
    svc = _with_user(system_user())
    app.dependency_overrides.pop(get_report_connection)
    r = TestClient(app).get(URL)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "AUTH_FORBIDDEN"
    svc.get_options.assert_not_called()


def test_lookup_forbidden_without_tenant_in_token() -> None:
    svc = _with_user(tenant_user(tenant_id=None))
    app.dependency_overrides.pop(get_report_connection)
    r = TestClient(app).get(URL)
    assert r.status_code == 403
    svc.get_options.assert_not_called()


def test_lookup_not_found() -> None:
    svc = _with_user(tenant_user())

    def _missing(*_: object, **__: object) -> None:
        not_found("REPORT_LOOKUP", "Lookup not found")

    svc.get_options.side_effect = _missing
    r = TestClient(app).get("/api/reports/tenant_account_list/lookups/created_date")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_LOOKUP_NOT_FOUND"
