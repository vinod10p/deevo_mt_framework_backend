"""``GET /api/auth/me`` for portal users (``user_scope=tenant_account``)."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from mtf.auth.api.session import (
    get_tenant_account_service_for_me,
    get_tenant_account_user_service,
    get_user_service,
)
from mtf.auth.models.tenant_account_user import TenantAccountUser
from main import app
from mtf.shared.deps import CurrentUser, get_current_user, get_permission_resolver

from tests.auth.test_system_auth_api import _minimal_user
from tests.tenant.conftest import (
    TEST_ACCOUNT_ID,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_tenant_account,
)


def test_me_tenant_account_returns_account_context() -> None:
    user = _minimal_user(
        id=TEST_USER_ID,
        user_scope="tenant_account",
    )
    membership = MagicMock(spec=TenantAccountUser)
    membership.is_active = True
    membership.role = "admin"

    account_svc = MagicMock()
    account_svc.get_by_id.return_value = minimal_tenant_account(
        name="Acme Corp",
        account_code="A001",
        account_type="customer",
    )

    user_svc = MagicMock()
    user_svc.get_user.return_value = user

    account_user_svc = MagicMock()
    account_user_svc.get_membership.return_value = membership

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant_account",
        tenant_id=TEST_TENANT_ID,
        account_id=TEST_ACCOUNT_ID,
    )
    resolver = MagicMock()
    resolver.permission_codes.return_value = frozenset()
    resolver.report_grants.return_value = {}
    app.dependency_overrides[get_user_service] = lambda: user_svc
    app.dependency_overrides[get_tenant_account_user_service] = lambda: account_user_svc
    app.dependency_overrides[get_tenant_account_service_for_me] = lambda: account_svc
    app.dependency_overrides[get_permission_resolver] = lambda: resolver

    client = TestClient(app)
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user_scope"] == "tenant_account"
    assert body["tenant_id"] == TEST_TENANT_ID
    assert body["account_id"] == TEST_ACCOUNT_ID
    assert body["account_name"] == "Acme Corp"
    assert body["account_code"] == "A001"
    assert body["role"] == "admin"
    assert body["permissions"] == []
    assert body["reports"] == []
