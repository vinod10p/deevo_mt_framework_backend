"""FastAPI tests — nav routes (``/api/nav/modules``, mocked service)."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.nav.api.menu import get_nav_menu_service
from mtf.nav.schemas import (
    NavMenuItemRead,
    NavModuleItemsRead,
    NavModuleListRead,
    NavModuleSummary,
)
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.shared.exceptions import not_found
from tests.nav.conftest import portal_user, system_user, tenant_user


def _list_body() -> NavModuleListRead:
    return NavModuleListRead(
        version="2026-11-16T08:12:34.567Z",
        modules=[
            NavModuleSummary(code="CRM", name="CRM", icon="crm", sort_order=10),
            NavModuleSummary(code="WF", name="Workflow", icon="workflow", sort_order=20),
        ],
    )


def _items_body() -> NavModuleItemsRead:
    return NavModuleItemsRead(
        version="2026-11-16T08:12:34.567Z",
        module=NavModuleSummary(code="CRM", name="CRM", icon="crm", sort_order=10),
        items=[
            NavMenuItemRead(
                code="CRM.LEADS",
                item_type="report",
                label="Leads",
                icon="users",
                report_key="crm_lead_list",
                screen_code=None,
                sort_order=10,
                children=[],
            ),
            NavMenuItemRead(
                code="CRM.SALES",
                item_type="group",
                label="Sales",
                icon="folder",
                report_key=None,
                screen_code=None,
                sort_order=20,
                children=[
                    NavMenuItemRead(
                        code="CRM.ACCOUNTS",
                        item_type="report",
                        label="Accounts",
                        icon="building",
                        report_key="crm_account_list",
                        screen_code=None,
                        sort_order=10,
                        children=[],
                    )
                ],
            ),
        ],
    )


def _with_user(user: CurrentUser) -> MagicMock:
    svc = MagicMock()
    svc.list_modules.return_value = _list_body()
    svc.get_module_items.return_value = _items_body()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_nav_menu_service] = lambda: svc
    return svc


def test_openapi_registers_nav_paths() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/nav/modules" in paths
    assert "/api/nav/modules/{module_code}/items" in paths


def test_nav_routes_require_bearer() -> None:
    client = TestClient(app)
    assert client.get("/api/nav/modules").status_code in (401, 403)
    assert client.get("/api/nav/modules/CRM/items").status_code in (401, 403)


def test_list_modules_tenant_ok() -> None:
    svc = _with_user(tenant_user())
    r = TestClient(app).get("/api/nav/modules")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "2026-11-16T08:12:34.567Z"
    assert [row["code"] for row in body["modules"]] == ["CRM", "WF"]
    assert "id" not in body["modules"][0]
    svc.list_modules.assert_called_once_with()


def test_list_modules_portal_and_system_allowed() -> None:
    for user in (portal_user(), system_user()):
        svc = _with_user(user)
        r = TestClient(app).get("/api/nav/modules")
        assert r.status_code == 200
        svc.list_modules.assert_called_once_with()


def test_get_module_items_nested_tree() -> None:
    svc = _with_user(tenant_user())
    r = TestClient(app).get("/api/nav/modules/CRM/items")
    assert r.status_code == 200
    body = r.json()
    svc.get_module_items.assert_called_once_with("CRM")
    assert body["module"]["code"] == "CRM"
    assert body["items"][0]["report_key"] == "crm_lead_list"
    assert body["items"][1]["item_type"] == "group"
    assert body["items"][1]["report_key"] is None
    assert body["items"][1]["screen_code"] is None
    assert body["items"][1]["children"][0]["code"] == "CRM.ACCOUNTS"
    assert "report_id" not in r.text
    assert "screen_id" not in r.text
    assert "module_id" not in r.text


def test_get_module_items_not_found() -> None:
    svc = _with_user(tenant_user())

    def _missing(*_: object) -> None:
        not_found("NAV_MODULE", "Module not found")

    svc.get_module_items.side_effect = _missing
    r = TestClient(app).get("/api/nav/modules/MISSING/items")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NAV_MODULE_NOT_FOUND"
