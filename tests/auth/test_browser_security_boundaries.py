"""Regression coverage for tenant identity writes and cookie auth."""

from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from mtf.auth.api import session as session_api
from mtf.auth.schemas.session import TokenResponse
from mtf.auth.services.tenant_account_user import TenantAccountUserService
from mtf.auth.services.tenant_user import TenantUserService
from mtf.shared.deps import CurrentUser

ORIGIN = "https://app.example.test"
COOKIE = "__Host-deevoflow-refresh-" + sha256(ORIGIN.encode()).hexdigest()[:32]


@pytest.mark.parametrize("portal", [False, True])
def test_scoped_admin_cannot_overwrite_existing_password(monkeypatch, portal):
    db = MagicMock()
    if portal:
        service = TenantAccountUserService(db)
        actor = CurrentUser(
            user_id="admin",
            user_type="app_user",
            user_scope="tenant_account",
            tenant_id="tenant",
            account_id="account",
        )
        args = ("tenant", "account")
        create, update = service.create_for_account, service.update_for_account
        monkeypatch.setattr(service, "_require_account", MagicMock())
        monkeypatch.setattr(service, "_membership", MagicMock(return_value=MagicMock()))
    else:
        service = TenantUserService(db)
        actor = CurrentUser(
            user_id="admin", user_type="app_user", user_scope="tenant", tenant_id="tenant"
        )
        args = ("tenant",)
        create, update = service.create_for_tenant, service.update_for_tenant
        monkeypatch.setattr(service, "_require_tenant", MagicMock())
        monkeypatch.setattr(
            service, "_membership_by_tenant_and_user", MagicMock(return_value=MagicMock())
        )

    existing = SimpleNamespace(id="existing", password_hash="original")
    monkeypatch.setattr(service, "_get_active_user_by_email", lambda email: existing)

    with pytest.raises(HTTPException) as creation:
        create(
            *args,
            SimpleNamespace(email="member@example.test", password="new-password"),
            actor=actor,
        )
    assert creation.value.status_code == 409

    with pytest.raises(HTTPException) as update_error:
        update(*args, "existing", SimpleNamespace(password="new-password"), actor=actor)
    assert update_error.value.status_code == 403
    assert existing.password_hash == "original"
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_browser_auth_cookie_round_trip(monkeypatch):
    monkeypatch.setattr(
        session_api,
        "get_settings",
        lambda: SimpleNamespace(
            allowed_origins=[ORIGIN, "https://adjacent.example.test"],
            jwt_refresh_token_expire_days=7,
        ),
    )
    monkeypatch.setattr(session_api, "decode_access_token", lambda token: {"sid": "session"})
    monkeypatch.setattr(
        session_api, "decode_refresh_token", lambda token: {"session_id": "session"}
    )
    service = MagicMock()
    service.logout_by_refresh.side_effect = lambda token, session_id, **kwargs: (
        session_id == "session"
    )
    service.login.return_value = TokenResponse(
        access_token="first-access",
        refresh_token="first-refresh",
        user_id="member",
        user_type="app_user",
        user_scope="tenant",
    )
    service.refresh.return_value = service.login.return_value.model_copy(
        update={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
        }
    )
    app = FastAPI()
    app.include_router(session_api.router)
    app.dependency_overrides[session_api.get_session_service] = lambda: service
    with TestClient(app, base_url="https://api.example.test") as client:
        denied = client.post(
            "/browser/login", json={"email": "member@example.test", "password": "test"}
        )
        assert denied.status_code == 403
        service.login.assert_not_called()

        client.headers["Origin"] = ORIGIN
        login = client.post(
            "/browser/login", json={"email": "member@example.test", "password": "test"}
        )
        assert login.status_code == 200
        assert login.headers["cache-control"] == "no-store"
        assert "refresh_token" not in login.json()
        assert login.json()["session_id"] == "session"
        assert {part.strip().lower() for part in login.headers["set-cookie"].split(";")[1:]} >= {
            "httponly",
            "secure",
            "samesite=strict",
            "path=/",
        }
        assert client.cookies.get(COOKIE) == "first-refresh"

        adjacent = client.post(
            "/browser/refresh",
            json={"session_id": "session"},
            headers={"Origin": "https://adjacent.example.test"},
        )
        assert adjacent.status_code == 401
        stale_refresh = client.post("/browser/refresh", json={"session_id": "stale"})
        assert stale_refresh.status_code == 401
        service.refresh.assert_not_called()
        refresh = client.post("/browser/refresh", json={"session_id": "session"})
        assert refresh.status_code == 200
        assert refresh.json()["access_token"] == "new-access"
        assert "refresh_token" not in refresh.json()
        assert service.refresh.call_args.args[0].refresh_token == "first-refresh"

        denied_logout = client.post(
            "/browser/logout", headers={"Origin": "https://other.example.test"}
        )
        assert denied_logout.status_code == 403
        service.logout_by_refresh.assert_not_called()
        stale_logout = client.post("/browser/logout", json={"session_id": "stale"})
        assert stale_logout.status_code == 403
        assert client.cookies.get(COOKIE) == "new-refresh"
        logout = client.post("/browser/logout", json={"session_id": "session"})
        assert logout.status_code == 204
        assert client.cookies.get(COOKIE) is None
        assert service.logout_by_refresh.call_args.args[0] == "new-refresh"
