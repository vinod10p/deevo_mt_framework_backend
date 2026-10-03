"""FastAPI tests — saved view write routes (mocked service)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.rpt.api.report import get_report_saved_view_service
from mtf.rpt.schemas import ReportSavedViewRead
from mtf.rpt.services import AuditSource
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.shared.exceptions import conflict
from tests.rpt.conftest import system_user, tenant_user

VIEWS_URL = "/api/reports/tenant_account_list/views"
VIEW_ID = "01JRPT0SV00000000000000001"
VIEW_URL = f"{VIEWS_URL}/{VIEW_ID}"
ROW_VERSION_B64 = "AAECAwQFBgc="


def _view(**overrides: object) -> ReportSavedViewRead:
    values: dict[str, object] = {
        "id": VIEW_ID,
        "view_name": "Q3 Review",
        "scope_type": "user",
        "is_default": False,
        "can_edit": True,
        "criteria": {},
        "layout": {"columns": [], "sort": [], "group": [], "aggregates": []},
        "row_version": bytes(range(8)),
        "updated_at": datetime(2026, 10, 2, 21, 52),
    }
    values.update(overrides)
    return ReportSavedViewRead(**values)  # type: ignore[arg-type]


def _with_user(user: CurrentUser) -> MagicMock:
    svc = MagicMock()
    svc.create_view.return_value = _view()
    svc.update_view.return_value = _view(view_name="Renamed")
    svc.delete_view.return_value = None
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_report_saved_view_service] = lambda: svc
    return svc


def test_openapi_registers_write_paths() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "post" in paths["/api/reports/{report_key}/views"]
    assert {"patch", "delete"} <= set(paths["/api/reports/{report_key}/views/{view_id}"])


def test_create_201_passes_body_and_audit_source() -> None:
    user = tenant_user()
    svc = _with_user(user)
    body = {
        "view_name": "  Q3 Review ",
        "scope_type": "user",
        "criteria": {"status": "active"},
        "layout": {"group": ["account_type"]},
        "is_default": True,
    }
    r = TestClient(app).post(VIEWS_URL, json=body, headers={"user-agent": "pytest-agent"})

    assert r.status_code == 201, r.text
    assert r.json()["row_version"] == ROW_VERSION_B64
    args, kwargs = svc.create_view.call_args
    assert args[:2] == (user, "tenant_account_list")
    assert args[2].view_name == "Q3 Review"
    assert args[2].criteria == {"status": "active"} and args[2].is_default is True
    assert isinstance(kwargs["source"], AuditSource)
    assert kwargs["source"].user_agent == "pytest-agent"


def test_create_defaults_criteria_and_layout_to_empty() -> None:
    svc = _with_user(tenant_user())
    r = TestClient(app).post(VIEWS_URL, json={"view_name": "x", "scope_type": "tenant"})
    assert r.status_code == 201
    data = svc.create_view.call_args.args[2]
    assert (data.criteria, data.layout, data.is_default) == ({}, {}, False)


def test_create_rejects_bad_bodies() -> None:
    svc = _with_user(tenant_user())
    client = TestClient(app)
    for body in (
        {"view_name": "   ", "scope_type": "user"},
        {"view_name": "x" * 201, "scope_type": "user"},
        {"view_name": "x", "scope_type": "global"},
        {"view_name": "x", "scope_type": "user", "user_id": "someone-else"},
        {"scope_type": "user"},
    ):
        assert client.post(VIEWS_URL, json=body).status_code == 422, body
    svc.create_view.assert_not_called()


def test_patch_decodes_row_version_and_passes_view_id() -> None:
    svc = _with_user(tenant_user())
    r = TestClient(app).patch(
        VIEW_URL, json={"row_version": ROW_VERSION_B64, "view_name": "Renamed"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["view_name"] == "Renamed"
    args = svc.update_view.call_args.args
    assert args[1:3] == ("tenant_account_list", VIEW_ID)
    assert args[3].row_version == bytes(range(8))
    assert args[3].criteria is None and args[3].layout is None


def test_patch_requires_row_version_and_rejects_scope_type() -> None:
    svc = _with_user(tenant_user())
    client = TestClient(app)
    assert client.patch(VIEW_URL, json={"view_name": "x"}).status_code == 422
    r = client.patch(VIEW_URL, json={"row_version": ROW_VERSION_B64, "scope_type": "tenant"})
    assert r.status_code == 422
    svc.update_view.assert_not_called()


def test_patch_conflict_shape() -> None:
    svc = _with_user(tenant_user())
    svc.update_view.side_effect = lambda *a, **k: conflict("REPORT_VIEW", "stale")
    r = TestClient(app).patch(VIEW_URL, json={"row_version": ROW_VERSION_B64})
    assert r.status_code == 409
    assert r.json() == {"detail": {"code": "REPORT_VIEW_CONFLICT", "message": "stale"}}


def test_delete_204() -> None:
    user = tenant_user()
    svc = _with_user(user)
    r = TestClient(app).delete(VIEW_URL)
    assert r.status_code == 204
    assert r.content == b""
    args, kwargs = svc.delete_view.call_args
    assert args == (user, "tenant_account_list", VIEW_ID)
    assert isinstance(kwargs["source"], AuditSource)


def test_writes_forbidden_for_system_scope() -> None:
    svc = _with_user(system_user())
    client = TestClient(app)
    assert client.post(VIEWS_URL, json={"view_name": "x", "scope_type": "user"}).status_code == 403
    assert client.patch(VIEW_URL, json={"row_version": ROW_VERSION_B64}).status_code == 403
    assert client.delete(VIEW_URL).status_code == 403
    svc.create_view.assert_not_called()
    svc.update_view.assert_not_called()
    svc.delete_view.assert_not_called()


def test_writes_require_bearer() -> None:
    client = TestClient(app)
    assert client.post(VIEWS_URL, json={}).status_code in (401, 403)
    assert client.delete(VIEW_URL).status_code in (401, 403)
