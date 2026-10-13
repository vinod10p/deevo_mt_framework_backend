"""require_screen_permission — FastAPI wiring on a probe app, not main."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from mtf.shared.deps import get_current_user
from mtf.txn.api.deps import get_screen_permission_service, require_screen_permission
from mtf.txn.services.screen_permission import ScreenEffectivePermissions
from tests.txn.conftest import SAMPLE_SCREEN_KEY, system_user, tenant_user

_ALLOWED = ScreenEffectivePermissions(
    can_view=True,
    can_add=True,
    can_edit=True,
    can_delete=False,
)
_ADD_ONLY = ScreenEffectivePermissions(
    can_view=False,
    can_add=True,
    can_edit=False,
    can_delete=False,
)
_DENIED = ScreenEffectivePermissions(
    can_view=False,
    can_add=False,
    can_edit=False,
    can_delete=False,
)


def _probe_app() -> FastAPI:
    app = FastAPI()

    @app.get("/probe-view")
    def probe_view(
        perms: ScreenEffectivePermissions = Depends(
            require_screen_permission(SAMPLE_SCREEN_KEY, "view")
        ),
    ) -> dict[str, bool]:
        return {"can_view": perms.can_view}

    @app.get("/probe-add")
    def probe_add(
        perms: ScreenEffectivePermissions = Depends(
            require_screen_permission(SAMPLE_SCREEN_KEY, "add")
        ),
    ) -> dict[str, bool]:
        return {"can_add": perms.can_add}

    return app


def _client(perms: ScreenEffectivePermissions, user=None) -> TestClient:
    app = _probe_app()
    svc = MagicMock()
    svc.resolve.return_value = perms
    app.dependency_overrides[get_current_user] = lambda: user or tenant_user()
    app.dependency_overrides[get_screen_permission_service] = lambda: svc
    return TestClient(app)


def test_view_allowed_returns_200() -> None:
    response = _client(_ALLOWED).get("/probe-view")
    assert response.status_code == 200
    assert response.json() == {"can_view": True}


def test_view_denied_returns_screen_forbidden() -> None:
    response = _client(_DENIED).get("/probe-view")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SCREEN_FORBIDDEN"


def test_add_only_user_can_hit_add_but_not_view() -> None:
    client = _client(_ADD_ONLY)
    add = client.get("/probe-add")
    view = client.get("/probe-view")
    assert add.status_code == 200
    assert view.status_code == 403
    assert view.json()["detail"]["code"] == "SCREEN_FORBIDDEN"


def test_missing_tenant_is_auth_forbidden() -> None:
    response = _client(_ALLOWED, user=system_user()).get("/probe-view")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "AUTH_FORBIDDEN"


def test_same_screen_and_operation_reuses_dependency() -> None:
    from mtf.txn.api import deps as deps_mod

    first = require_screen_permission(SAMPLE_SCREEN_KEY, "view")
    second = require_screen_permission(SAMPLE_SCREEN_KEY, "view")
    assert first is second
    assert (SAMPLE_SCREEN_KEY, "view") in deps_mod._screen_permission_checkers
