"""require_permission — FastAPI wiring on a probe app, not main."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.shared.deps import (
    PERMISSION_RESOLVER_STATE,
    CurrentUser,
    get_current_user,
    get_db,
    get_permission_resolver,
    require_permission,
)

TEST_TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE0"
TEST_USER_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE3"
VIEW = "screen.lead.view"
CREATE = "screen.lead.create"


def tenant_user() -> CurrentUser:
    return CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant",
        tenant_id=TEST_TENANT_ID,
    )


def _probe_app() -> FastAPI:
    app = FastAPI()

    @app.get("/one")
    def one(user: CurrentUser = Depends(require_permission(VIEW))) -> dict[str, str]:
        return {"user_id": user.user_id}

    @app.get("/two")
    def two(
        _view: CurrentUser = Depends(require_permission(VIEW)),
        _create: CurrentUser = Depends(require_permission(CREATE)),
    ) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/state")
    def state(
        request: Request,
        resolver: PermissionResolver = Depends(get_permission_resolver),
    ) -> dict[str, bool]:
        stored = getattr(request.state, PERMISSION_RESOLVER_STATE, None)
        return {"same": stored is resolver}

    return app


def test_granted_permission_returns_200() -> None:
    app = _probe_app()
    resolver = MagicMock()
    resolver.has_permission.return_value = True
    app.dependency_overrides[get_current_user] = tenant_user
    app.dependency_overrides[get_permission_resolver] = lambda: resolver
    response = TestClient(app).get("/one")
    assert response.status_code == 200
    assert response.json() == {"user_id": TEST_USER_ID}


def test_missing_permission_returns_auth_forbidden() -> None:
    app = _probe_app()
    resolver = MagicMock()
    resolver.has_permission.return_value = False
    app.dependency_overrides[get_current_user] = tenant_user
    app.dependency_overrides[get_permission_resolver] = lambda: resolver
    response = TestClient(app).get("/one")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "AUTH_FORBIDDEN"


def test_two_require_permission_calls_query_once() -> None:
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = [VIEW, CREATE]
    db.scalars.return_value = result
    resolver = PermissionResolver(db)

    app = _probe_app()
    app.dependency_overrides[get_current_user] = tenant_user
    app.dependency_overrides[get_permission_resolver] = lambda: resolver
    response = TestClient(app).get("/two")
    assert response.status_code == 200
    assert db.scalars.call_count == 1


def test_same_code_reuses_dependency() -> None:
    first = require_permission(VIEW)
    second = require_permission(VIEW)
    assert first is second


def test_resolver_is_stored_on_request_state() -> None:
    app = _probe_app()
    db = MagicMock()
    app.dependency_overrides[get_current_user] = tenant_user
    app.dependency_overrides[get_db] = lambda: db
    response = TestClient(app).get("/state")
    assert response.status_code == 200
    assert response.json() == {"same": True}
