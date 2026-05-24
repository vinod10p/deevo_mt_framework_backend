"""Auth login — ``user_scope=tenant_account`` (portal) behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from mtf.auth.api.session import get_session_service
from mtf.auth.models.tenant_account_user import TenantAccountUser
from mtf.auth.schemas.session import TokenResponse
from mtf.auth.services.session_service import SessionService
from main import app

from tests.tenant.conftest import TEST_ACCOUNT_ID, TEST_TENANT_ID, TEST_USER_ID


def test_login_endpoint_returns_account_fields() -> None:
    svc = MagicMock()
    svc.login.return_value = TokenResponse(
        access_token="access",
        refresh_token="refresh",
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant_account",
        tenant_id=TEST_TENANT_ID,
        account_id=TEST_ACCOUNT_ID,
        account_name="Acme Corp",
        tenant_name="Test Tenant Org",
        first_name="Bob",
        last_name="Buyer",
    )
    app.dependency_overrides[get_session_service] = lambda: svc

    client = TestClient(app)
    r = client.post(
        "/api/auth/login",
        json={
            "email": "portal@example.com",
            "password": "password123",
            "tenant_id": TEST_TENANT_ID,
            "created_from": "web",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_scope"] == "tenant_account"
    assert body["account_id"] == TEST_ACCOUNT_ID
    assert body["account_name"] == "Acme Corp"
    svc.login.assert_called_once()


def test_require_single_account_membership_zero() -> None:
    service = SessionService(MagicMock())
    with patch.object(service, "_list_active_account_memberships", return_value=[]):
        with pytest.raises(HTTPException) as exc:
            service._require_single_account_membership(TEST_USER_ID, TEST_TENANT_ID)
        assert exc.value.status_code == 401


def test_require_single_account_membership_multiple() -> None:
    service = SessionService(MagicMock())
    m1 = MagicMock(spec=TenantAccountUser)
    m1.account_id = "01ACCOUNT0000000000000001"
    m2 = MagicMock(spec=TenantAccountUser)
    m2.account_id = "01ACCOUNT0000000000000002"
    with patch.object(service, "_list_active_account_memberships", return_value=[m1, m2]):
        with pytest.raises(HTTPException) as exc:
            service._require_single_account_membership(TEST_USER_ID, TEST_TENANT_ID)
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "MULTIPLE_ACCOUNT_MEMBERSHIPS"


def test_require_single_account_membership_one() -> None:
    service = SessionService(MagicMock())
    m1 = MagicMock(spec=TenantAccountUser)
    m1.account_id = TEST_ACCOUNT_ID
    with patch.object(service, "_list_active_account_memberships", return_value=[m1]):
        account_id = service._require_single_account_membership(TEST_USER_ID, TEST_TENANT_ID)
    assert account_id == TEST_ACCOUNT_ID
