"""Shared helpers — txn tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime

import pytest

from mtf.shared.deps import CurrentUser
from mtf.txn.models import (
    Lookup,
    LookupColumn,
    Screen,
    ScreenField,
    ScreenFieldConfig,
    ScreenPermission,
    ScreenSection,
)

_NOW = datetime(2026, 10, 11, 12, 0, 0)
_ROW_VER = bytes(range(8))

TEST_TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE0"
TEST_USER_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE3"
SAMPLE_SCREEN_ID = "01JTXNSCR00000000000000001"
SAMPLE_SCREEN_KEY = "sample_screen"
SAMPLE_PERM_ID = "01JTXNPERM0000000000000001"
SAMPLE_SECTION_ID = "01JTXNSEC0000000000000001"
SAMPLE_FIELD_ID = "01JTXNFLD0000000000000001"
SAMPLE_LOOKUP_ID = "01JTXNLKP0000000000000001"
SAMPLE_LOOKUP_COL_ID = "01JTXNLKC0000000000000001"
SAMPLE_CONFIG_ID = "01JTXNCFG0000000000000001"
TEST_ACCOUNT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE1"


@pytest.fixture(autouse=True)
def clear_app_dependency_overrides() -> Generator[None, None, None]:
    from main import app

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


def system_user() -> CurrentUser:
    return CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )


def portal_user() -> CurrentUser:
    return CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant_account",
        tenant_id=TEST_TENANT_ID,
        account_id=TEST_ACCOUNT_ID,
    )


def _audit_fields() -> dict[str, object]:
    return {
        "is_active": True,
        "is_deleted": False,
        "row_version": _ROW_VER,
        "created_at": _NOW,
        "updated_at": _NOW,
        "created_by": None,
        "updated_by": None,
        "deleted_at": None,
        "deleted_by": None,
    }


def minimal_screen(**kwargs: object) -> Screen:
    base: dict[str, object] = {
        "id": SAMPLE_SCREEN_ID,
        "screen_key": SAMPLE_SCREEN_KEY,
        "display_name": "Sample Screen",
        "description": None,
        "api_base_path": "/api/samples",
        "layout_type": "standard",
        "permission_mode": "open",
        "allow_view": True,
        "allow_add": True,
        "allow_edit": True,
        "allow_delete": False,
        **_audit_fields(),
    }
    base.update(kwargs)
    return Screen(**base)


def minimal_permission(**kwargs: object) -> ScreenPermission:
    base: dict[str, object] = {
        "id": SAMPLE_PERM_ID,
        "tenant_id": TEST_TENANT_ID,
        "user_id": TEST_USER_ID,
        "screen_id": SAMPLE_SCREEN_ID,
        "can_access": True,
        "can_view": True,
        "can_add": True,
        "can_edit": True,
        "can_delete": False,
        **_audit_fields(),
    }
    base.update(kwargs)
    return ScreenPermission(**base)


def minimal_section(**kwargs: object) -> ScreenSection:
    base: dict[str, object] = {
        "id": SAMPLE_SECTION_ID,
        "screen_id": SAMPLE_SCREEN_ID,
        "section_key": "general",
        "display_name": "General",
        "display_order": 10,
        "column_count": 2,
        "is_collapsible": False,
        "is_collapsed_default": False,
        **_audit_fields(),
    }
    base.update(kwargs)
    return ScreenSection(**base)


def minimal_field(**kwargs: object) -> ScreenField:
    base: dict[str, object] = {
        "id": SAMPLE_FIELD_ID,
        "screen_id": SAMPLE_SCREEN_ID,
        "section_id": SAMPLE_SECTION_ID,
        "field_key": "name",
        "display_name": "Name",
        "data_type": "string",
        "control_type": "text",
        "display_order": 10,
        "column_span": 1,
        "is_displayed": True,
        "is_required": True,
        "edit_mode": "editable",
        "default_value": None,
        "lookup_id": None,
        "max_length": 150,
        "min_value": None,
        "max_value": None,
        "format_type": None,
        "help_text": None,
        **_audit_fields(),
    }
    base.update(kwargs)
    return ScreenField(**base)


def minimal_config(**kwargs: object) -> ScreenFieldConfig:
    base: dict[str, object] = {
        "id": SAMPLE_CONFIG_ID,
        "tenant_id": TEST_TENANT_ID,
        "field_id": SAMPLE_FIELD_ID,
        "display_name": None,
        "display_order": None,
        "is_displayed": None,
        **_audit_fields(),
    }
    base.update(kwargs)
    return ScreenFieldConfig(**base)


def minimal_lookup(**kwargs: object) -> Lookup:
    base: dict[str, object] = {
        "id": SAMPLE_LOOKUP_ID,
        "lookup_key": "sample_lookup",
        "display_name": "Sample Lookup",
        "api_base_path": "/api/lookups/samples",
        "return_field_key": "id",
        "display_field_key": "name",
        "min_search_chars": 2,
        "page_size": 50,
        **_audit_fields(),
    }
    base.update(kwargs)
    return Lookup(**base)


def minimal_lookup_column(**kwargs: object) -> LookupColumn:
    base: dict[str, object] = {
        "id": SAMPLE_LOOKUP_COL_ID,
        "lookup_id": SAMPLE_LOOKUP_ID,
        "field_key": "name",
        "display_name": "Name",
        "display_order": 10,
        "is_displayed": True,
        "is_searchable": True,
        "width": None,
        "format_type": None,
        **_audit_fields(),
    }
    base.update(kwargs)
    return LookupColumn(**base)
