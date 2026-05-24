"""Shared helpers — tenant tests (no database)."""

from __future__ import annotations

from datetime import datetime

import pytest

from mtf.tenant.models import Tenant, TenantAccount, TenantAccountAddress


@pytest.fixture(autouse=True)
def clear_app_dependency_overrides() -> None:
    """Isolation for FastAPI ``dependency_overrides`` across tenant API tests."""
    from main import app

    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()

_NOW = datetime(2026, 5, 9, 12, 0, 0)
_ROW_VER = bytes(range(8))

# Crockford ULIDs — exactly 26 chars (matches ``varchar(26)`` PKs).
TEST_TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE0"
TEST_ACCOUNT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE1"
TEST_ADDRESS_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE2"
TEST_USER_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE3"
TEST_SYSTEM_USER_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE4"
SEEDED_SYSTEM_USER_ID = "01HYSTEM00000000000000000"


def minimal_tenant(**kwargs: object) -> Tenant:
    base: dict[str, object] = {
        "id": TEST_TENANT_ID,
        "name": "Test Tenant Org",
        "subdomain": "test-tenant-org",
        "status": "trial",
        "is_active": True,
        "is_deleted": False,
        "plan_type": "trial",
        "max_users": 10,
        "max_agents": 5,
        "max_contacts": 10_000,
        "storage_limit_gb": 10,
        "timezone": "UTC",
        "locale": "en-US",
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by": None,
        "updated_by": None,
        "deleted_by": None,
        "billing_email": None,
        "contact_email": None,
        "contact_phone": None,
        "address_line1": None,
        "address_line2": None,
        "city": None,
        "state": None,
        "postal_code": None,
        "country": None,
        "logo_url": None,
        "settings": None,
        "features_enabled": None,
        "subscription_start_date": None,
        "subscription_end_date": None,
    }
    base.update(kwargs)
    return Tenant(**base)


def minimal_tenant_account(**kwargs: object) -> TenantAccount:
    base: dict[str, object] = {
        "id": TEST_ACCOUNT_ID,
        "tenant_id": TEST_TENANT_ID,
        "account_code": "A001",
        "account_type": "customer",
        "name": "Acme Corp",
        "email": None,
        "phone": None,
        "website": None,
        "custom_fields": None,
        "status": "active",
        "is_active": True,
        "is_deleted": False,
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by": None,
        "updated_by": None,
        "deleted_by": None,
    }
    base.update(kwargs)
    return TenantAccount(**base)


def minimal_tenant_account_address(**kwargs: object) -> TenantAccountAddress:
    base: dict[str, object] = {
        "id": TEST_ADDRESS_ID,
        "tenant_id": TEST_TENANT_ID,
        "account_id": TEST_ACCOUNT_ID,
        "address_type": "billing",
        "is_default": False,
        "address_line1": "1 Main St",
        "address_line2": None,
        "city": None,
        "state": None,
        "postal_code": None,
        "country": None,
        "is_active": True,
        "is_deleted": False,
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by": None,
        "updated_by": None,
        "deleted_by": None,
    }
    base.update(kwargs)
    return TenantAccountAddress(**base)


def minimal_tenant_user_detail(**kwargs: object) -> dict[str, object]:
    base: dict[str, object] = {
        "tenant_user_id": "01HZYJZGXM0KV0K4T8Y9ABCDE5",
        "tenant_id": TEST_TENANT_ID,
        "user_id": TEST_USER_ID,
        "email": "member@example.com",
        "first_name": "Member",
        "last_name": "User",
        "phone": None,
        "avatar_url": None,
        "user_scope": "tenant",
        "last_login_at": None,
        "is_deleted": False,
        "role": "member",
        "is_active": True,
        "joined_at": _NOW,
        "invited_at": None,
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by": TEST_SYSTEM_USER_ID,
        "updated_by": TEST_SYSTEM_USER_ID,
        "deleted_by": None,
    }
    base.update(kwargs)
    return base


def minimal_tenant_account_user_detail(**kwargs: object) -> dict[str, object]:
    base: dict[str, object] = {
        "tenant_account_user_id": "01HZYJZGXM0KV0K4T8Y9ABCDE6",
        "tenant_id": TEST_TENANT_ID,
        "account_id": TEST_ACCOUNT_ID,
        "user_id": TEST_USER_ID,
        "email": "portal@example.com",
        "first_name": "Portal",
        "last_name": "User",
        "phone": None,
        "avatar_url": None,
        "user_scope": "tenant_account",
        "last_login_at": None,
        "role": "member",
        "is_active": True,
        "is_deleted": False,
        "joined_at": _NOW,
        "invited_at": None,
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by": TEST_SYSTEM_USER_ID,
        "updated_by": TEST_SYSTEM_USER_ID,
        "deleted_by": None,
    }
    base.update(kwargs)
    return base
