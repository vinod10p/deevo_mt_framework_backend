"""FastAPI tests — ``GET /api/screens/{screen_key}`` (mocked service)."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.shared.exceptions import not_found
from mtf.txn.api.screen import get_screen_metadata_service
from mtf.txn.schemas import (
    ScreenFieldRead,
    ScreenMetadataRead,
    ScreenPermissionsRead,
    ScreenSectionRead,
)
from tests.txn.conftest import (
    SAMPLE_SCREEN_KEY,
    TEST_TENANT_ID,
    TEST_USER_ID,
    portal_user,
    system_user,
    tenant_user,
)


def _metadata() -> ScreenMetadataRead:
    return ScreenMetadataRead(
        screen_key=SAMPLE_SCREEN_KEY,
        display_name="Sample Screen",
        layout_type="standard",
        api_base_path="/api/samples",
        permissions=ScreenPermissionsRead(
            can_view=True, can_add=True, can_edit=True, can_delete=False
        ),
        sections=[
            ScreenSectionRead(
                section_key="general",
                display_name="General",
                display_order=10,
                column_count=2,
                is_collapsible=False,
                is_collapsed_default=False,
                fields=[
                    ScreenFieldRead(
                        field_key="name",
                        display_name="Name",
                        data_type="string",
                        control_type="text",
                        display_order=10,
                        column_span=1,
                        is_required=True,
                        edit_mode="editable",
                        default_value=None,
                        max_length=150,
                        min_value=None,
                        max_value=None,
                        format_type=None,
                        help_text=None,
                        lookup=None,
                    )
                ],
            )
        ],
    )


def _with_user(user: CurrentUser) -> MagicMock:
    svc = MagicMock()
    svc.get_screen.return_value = _metadata()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_screen_metadata_service] = lambda: svc
    return svc


def test_openapi_registers_screen_path() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/api/screens/{screen_key}" in paths


def test_screen_route_requires_bearer() -> None:
    r = TestClient(app).get(f"/api/screens/{SAMPLE_SCREEN_KEY}")
    assert r.status_code in (401, 403)


def test_get_screen_uses_jwt_tenant_and_user() -> None:
    svc = _with_user(tenant_user())
    r = TestClient(app).get(f"/api/screens/{SAMPLE_SCREEN_KEY}")
    assert r.status_code == 200
    svc.get_screen.assert_called_once_with(TEST_TENANT_ID, TEST_USER_ID, SAMPLE_SCREEN_KEY)
    body = r.json()
    assert body["screen_key"] == SAMPLE_SCREEN_KEY
    assert body["permissions"]["can_delete"] is False
    assert "id" not in body
    assert "capabilities" not in body


def test_get_screen_allows_portal_scope() -> None:
    svc = _with_user(portal_user())
    r = TestClient(app).get(f"/api/screens/{SAMPLE_SCREEN_KEY}")
    assert r.status_code == 200
    svc.get_screen.assert_called_once_with(TEST_TENANT_ID, TEST_USER_ID, SAMPLE_SCREEN_KEY)


def test_get_screen_forbidden_without_tenant() -> None:
    svc = _with_user(system_user())
    r = TestClient(app).get(f"/api/screens/{SAMPLE_SCREEN_KEY}")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "AUTH_FORBIDDEN"
    svc.get_screen.assert_not_called()


def test_get_screen_not_found() -> None:
    svc = _with_user(tenant_user())

    def _missing(*_: object) -> None:
        not_found("SCREEN", "Screen not found")

    svc.get_screen.side_effect = _missing
    r = TestClient(app).get("/api/screens/does_not_exist")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SCREEN_NOT_FOUND"
