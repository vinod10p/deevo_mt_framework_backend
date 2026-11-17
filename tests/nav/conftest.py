"""Shared helpers — nav tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime

import pytest

from mtf.nav.models import MenuItem, MenuModule
from mtf.rpt.models import ReportDefinition
from mtf.shared.deps import CurrentUser

TEST_TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE0"
TEST_ACCOUNT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE1"
TEST_USER_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE3"
MODULE_ID = "01JNAVMTFMD000000000000001"
GROUP_ID = "01JNAVMTFME000000000000006"
REPORT_ITEM_ID = "01JNAVMTFME000000000000001"
CHILD_ITEM_ID = "01JNAVMTFME000000000000007"
REPORT_ID = "01JRPT0DF00000000000000001"
_NOW = datetime(2026, 11, 16, 8, 12, 34, 567000)
_ROW_VER = bytes(range(8))


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


def minimal_module(**kwargs: object) -> MenuModule:
    base: dict[str, object] = {
        "id": MODULE_ID,
        "code": "CRM",
        "name": "CRM",
        "icon": "crm",
        "user_scope": "tenant",
        "sort_order": 10,
        **_audit_fields(),
    }
    base.update(kwargs)
    return MenuModule(**base)  # type: ignore[arg-type]


def minimal_item(**kwargs: object) -> MenuItem:
    base: dict[str, object] = {
        "id": REPORT_ITEM_ID,
        "module_id": MODULE_ID,
        "parent_id": None,
        "code": "CRM.LEADS",
        "item_type": "report",
        "label": "Leads",
        "icon": "users",
        "report_id": REPORT_ID,
        "sort_order": 10,
        **_audit_fields(),
    }
    base.update(kwargs)
    return MenuItem(**base)  # type: ignore[arg-type]


def minimal_report(**kwargs: object) -> ReportDefinition:
    base: dict[str, object] = {
        "id": REPORT_ID,
        "tenant_id": None,
        "scope_type": "system",
        "report_key": "crm_lead_list",
        "display_name": "Lead List",
        "proc_name": "rpt.usp_crm_lead_list",
        "description": None,
        "default_max_rows": 20000,
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
    return ReportDefinition(**base)  # type: ignore[arg-type]
