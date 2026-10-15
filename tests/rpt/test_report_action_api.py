"""FastAPI tests — ``POST /api/reports/{report_key}/actions/{action_key}/resolve``."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.rpt.api.report import get_report_action_service
from mtf.rpt.schemas import ScreenNavigationRead
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.shared.exceptions import not_found, validation_error
from tests.rpt.conftest import TEST_TENANT_ID, TEST_USER_ID, portal_user, system_user, tenant_user

URL = "/api/reports/tenant_account_list/actions/open_sample/resolve"


def _with_user(user: CurrentUser) -> MagicMock:
    svc = MagicMock()
    svc.resolve.return_value = ScreenNavigationRead(
        screen_key="sample_screen",
        mode="view",
        params={"id": "01JSAMPLE0000000000000001"},
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_report_action_service] = lambda: svc
    return svc


def test_openapi_registers_resolve_path() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "post" in paths["/api/reports/{report_key}/actions/{action_key}/resolve"]


def test_resolve_requires_bearer() -> None:
    assert TestClient(app).post(URL, json={}).status_code in (401, 403)


def test_resolve_passes_body_and_returns_navigation() -> None:
    svc = _with_user(tenant_user())
    body = {"row": {"record_id": "01JSAMPLE0000000000000001"}, "criteria": {}}
    r = TestClient(app).post(URL, json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "target_type": "screen",
        "screen_key": "sample_screen",
        "mode": "view",
        "params": {"id": "01JSAMPLE0000000000000001"},
    }
    svc.resolve.assert_called_once_with(
        TEST_TENANT_ID,
        TEST_USER_ID,
        "tenant_account_list",
        "open_sample",
        row={"record_id": "01JSAMPLE0000000000000001"},
        criteria={},
    )


def test_resolve_empty_body_defaults() -> None:
    svc = _with_user(portal_user())
    r = TestClient(app).post(URL, json={})
    assert r.status_code == 200
    svc.resolve.assert_called_once_with(
        TEST_TENANT_ID,
        TEST_USER_ID,
        "tenant_account_list",
        "open_sample",
        row={},
        criteria={},
    )


def test_resolve_rejects_unknown_top_level_keys() -> None:
    svc = _with_user(tenant_user())
    r = TestClient(app).post(URL, json={"row": {}, "extra": True})
    assert r.status_code == 422
    svc.resolve.assert_not_called()


def test_resolve_forbidden_for_system_scope() -> None:
    svc = _with_user(system_user())
    r = TestClient(app).post(URL, json={})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "AUTH_FORBIDDEN"
    svc.resolve.assert_not_called()


def test_resolve_action_not_found() -> None:
    svc = _with_user(tenant_user())

    def _missing(*_: object, **__: object) -> None:
        not_found("REPORT_ACTION", "Action not found")

    svc.resolve.side_effect = _missing
    r = TestClient(app).post(URL, json={})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_ACTION_NOT_FOUND"


def test_resolve_invalid_sources() -> None:
    svc = _with_user(tenant_user())

    def _invalid(*_: object, **__: object) -> None:
        validation_error("REPORT_ACTION", "Action could not be resolved", {"record_id": "Required"})

    svc.resolve.side_effect = _invalid
    r = TestClient(app).post(URL, json={"row": {}})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "REPORT_ACTION_INVALID"
    assert r.json()["detail"]["fields"]["record_id"] == "Required"
