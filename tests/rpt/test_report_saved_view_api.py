"""FastAPI tests — saved view read routes (mocked service)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.rpt.api.report import get_report_saved_view_service
from mtf.rpt.schemas import ReportSavedViewRead
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.shared.exceptions import not_found
from tests.rpt.conftest import portal_user, system_user, tenant_user

LIST_URL = "/api/reports/tenant_account_list/views"
DEFAULT_URL = "/api/reports/tenant_account_list/views/default"


def _view(**overrides: object) -> ReportSavedViewRead:
    values: dict[str, object] = {
        "id": "01JRPT0SV00000000000000001",
        "view_name": "Q3 Review",
        "scope_type": "tenant",
        "is_default": True,
        "can_edit": False,
        "criteria": {"status": "active"},
        "layout": {"columns": [], "sort": [], "group": [], "aggregates": []},
        "row_version": bytes(range(8)),
        "updated_at": datetime(2026, 10, 2, 21, 52),
    }
    values.update(overrides)
    return ReportSavedViewRead(**values)  # type: ignore[arg-type]


def _with_user(user: CurrentUser) -> MagicMock:
    svc = MagicMock()
    svc.list_views.return_value = [_view()]
    svc.get_default_view.return_value = _view()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_report_saved_view_service] = lambda: svc
    return svc


def test_openapi_registers_view_paths() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "get" in paths["/api/reports/{report_key}/views"]
    assert "get" in paths["/api/reports/{report_key}/views/default"]


def test_views_require_bearer() -> None:
    client = TestClient(app)
    assert client.get(LIST_URL).status_code in (401, 403)
    assert client.get(DEFAULT_URL).status_code in (401, 403)


def test_list_views_shape() -> None:
    user = tenant_user()
    svc = _with_user(user)
    r = TestClient(app).get(LIST_URL)
    assert r.status_code == 200
    assert r.json() == [
        {
            "id": "01JRPT0SV00000000000000001",
            "view_name": "Q3 Review",
            "scope_type": "tenant",
            "is_default": True,
            "can_edit": False,
            "criteria": {"status": "active"},
            "layout": {"columns": [], "sort": [], "group": [], "aggregates": []},
            "row_version": "AAECAwQFBgc=",
            "updated_at": "2026-10-02T21:52:00",
        }
    ]
    svc.list_views.assert_called_once_with(user, "tenant_account_list")


def test_default_view_returned() -> None:
    svc = _with_user(portal_user())
    r = TestClient(app).get(DEFAULT_URL)
    assert r.status_code == 200
    assert r.json()["scope_type"] == "tenant"
    svc.get_default_view.assert_called_once()


def test_default_view_204_when_none() -> None:
    svc = _with_user(tenant_user())
    svc.get_default_view.return_value = None
    r = TestClient(app).get(DEFAULT_URL)
    assert r.status_code == 204
    assert r.content == b""


def test_views_forbidden_for_system_scope_and_missing_tenant() -> None:
    for user in (system_user(), tenant_user(tenant_id=None)):
        svc = _with_user(user)
        client = TestClient(app)
        assert client.get(LIST_URL).status_code == 403
        assert client.get(DEFAULT_URL).status_code == 403
        svc.list_views.assert_not_called()
        svc.get_default_view.assert_not_called()


def test_views_report_not_found() -> None:
    svc = _with_user(tenant_user())

    def _missing(*_: object) -> None:
        not_found("REPORT", "Report not found")

    svc.list_views.side_effect = _missing
    svc.get_default_view.side_effect = _missing
    client = TestClient(app)
    for url in ("/api/reports/nope/views", "/api/reports/nope/views/default"):
        r = client.get(url)
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "REPORT_NOT_FOUND"
