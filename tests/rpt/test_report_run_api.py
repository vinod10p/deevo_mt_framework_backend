"""FastAPI tests — ``POST /api/reports/{report_key}/run`` (mocked service)."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.rpt.api.deps import get_report_connection
from mtf.rpt.api.report import get_report_run_service
from mtf.rpt.schemas import ReportRunRead
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.shared.exceptions import not_found, validation_error
from tests.rpt.conftest import TEST_TENANT_ID, portal_user, system_user, tenant_user

URL = "/api/reports/tenant_account_list/run"
CONN = object()


def _with_user(user: CurrentUser) -> MagicMock:
    svc = MagicMock()
    svc.run.return_value = ReportRunRead(
        report_key="tenant_account_list",
        row_count=1,
        truncated=False,
        rows=[{"name": "Acme", "amount": 10.5, "created_at": "2026-03-01T09:00:00"}],
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_report_run_service] = lambda: svc
    app.dependency_overrides[get_report_connection] = lambda: CONN
    return svc


def test_openapi_registers_run_path() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "post" in paths["/api/reports/{report_key}/run"]


def test_run_requires_bearer() -> None:
    assert TestClient(app).post(URL, json={}).status_code in (401, 403)


def test_run_passes_body_and_returns_rows() -> None:
    svc = _with_user(tenant_user())
    body = {"criteria": {"status": "active"}, "max_rows": 100}
    r = TestClient(app).post(URL, json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "report_key": "tenant_account_list",
        "row_count": 1,
        "truncated": False,
        "rows": [{"name": "Acme", "amount": 10.5, "created_at": "2026-03-01T09:00:00"}],
    }
    svc.run.assert_called_once_with(
        CONN, TEST_TENANT_ID, "tenant_account_list", criteria={"status": "active"}, max_rows=100
    )


def test_run_empty_body_defaults() -> None:
    svc = _with_user(portal_user())
    r = TestClient(app).post(URL, json={})
    assert r.status_code == 200
    svc.run.assert_called_once_with(
        CONN, TEST_TENANT_ID, "tenant_account_list", criteria={}, max_rows=None
    )


def test_run_criteria_must_be_object() -> None:
    svc = _with_user(tenant_user())
    r = TestClient(app).post(URL, json={"criteria": ["status"]})
    assert r.status_code == 422
    svc.run.assert_not_called()


def test_run_forbidden_for_system_scope() -> None:
    svc = _with_user(system_user())
    app.dependency_overrides.pop(get_report_connection)
    r = TestClient(app).post(URL, json={})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "AUTH_FORBIDDEN"
    svc.run.assert_not_called()


def test_run_not_found() -> None:
    svc = _with_user(tenant_user())

    def _missing(*_: object, **__: object) -> None:
        not_found("REPORT", "Report not found")

    svc.run.side_effect = _missing
    r = TestClient(app).post("/api/reports/nope/run", json={})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_NOT_FOUND"


def test_run_criteria_invalid_shape() -> None:
    svc = _with_user(tenant_user())

    def _invalid(*_: object, **__: object) -> None:
        validation_error("REPORT_CRITERIA", "Invalid report criteria", {"status": "Bad"})

    svc.run.side_effect = _invalid
    r = TestClient(app).post(URL, json={"criteria": {"status": 1}})
    assert r.status_code == 422
    assert r.json() == {
        "detail": {
            "code": "REPORT_CRITERIA_INVALID",
            "message": "Invalid report criteria",
            "fields": {"status": "Bad"},
        }
    }
