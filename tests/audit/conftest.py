"""Shared helpers — audit API tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from main import app
from mtf.shared.deps import CurrentUser

TEST_TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE0"
OTHER_TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE9"
TEST_ACCOUNT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE1"
OTHER_ACCOUNT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE2"
TEST_USER_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE3"
LOG_ID = "01JAUDITLOG0000000000000001"


@pytest.fixture(autouse=True)
def clear_app_dependency_overrides() -> Generator[None, None, None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def tenant_user(tenant_id: str | None = TEST_TENANT_ID) -> CurrentUser:
    return CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant",
        tenant_id=tenant_id,
    )


def portal_user() -> CurrentUser:
    return CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant_account",
        tenant_id=TEST_TENANT_ID,
        account_id=TEST_ACCOUNT_ID,
    )


def system_user() -> CurrentUser:
    return CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
