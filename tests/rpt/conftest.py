"""Shared helpers — rpt tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime

import pytest

from mtf.rpt.models import ReportColumn, ReportCriteria, ReportDefinition, ReportSavedView
from mtf.shared.deps import CurrentUser


@pytest.fixture(autouse=True)
def clear_app_dependency_overrides() -> Generator[None, None, None]:
    from main import app

    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


_NOW = datetime(2026, 9, 30, 12, 0, 0)
_ROW_VER = bytes(range(8))

TEST_TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE0"
OTHER_TENANT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE9"
TEST_ACCOUNT_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE1"
TEST_USER_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE3"
SYSTEM_REPORT_ID = "01JRPT0DF00000000000000001"
TENANT_REPORT_ID = "01JRPT0DF00000000000000002"


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
        "deleted_by": None,
    }


def minimal_report(**kwargs: object) -> ReportDefinition:
    base: dict[str, object] = {
        "id": SYSTEM_REPORT_ID,
        "tenant_id": None,
        "scope_type": "system",
        "report_key": "tenant_account_list",
        "display_name": "Account List",
        "proc_name": "rpt.usp_tenant_account_list",
        "description": "All accounts",
        "default_max_rows": 20000,
        **_audit_fields(),
    }
    base.update(kwargs)
    return ReportDefinition(**base)  # type: ignore[arg-type]


def minimal_column(**kwargs: object) -> ReportColumn:
    base: dict[str, object] = {
        "id": "01JRPT0CM00000000000000001",
        "report_id": SYSTEM_REPORT_ID,
        "column_name": "name",
        "display_name": "Name",
        "data_type": "string",
        "display_order": 10,
        "is_displayable": True,
        "is_default_visible": True,
        "is_sortable": True,
        "is_groupable": False,
        "is_filterable": True,
        "is_aggregatable": False,
        "default_aggregate_type": None,
        "display_format": None,
        "default_width": 240,
        **_audit_fields(),
    }
    base.update(kwargs)
    return ReportColumn(**base)  # type: ignore[arg-type]


def minimal_saved_view(**kwargs: object) -> ReportSavedView:
    base: dict[str, object] = {
        "id": "01JRPT0SV00000000000000001",
        "tenant_id": TEST_TENANT_ID,
        "report_id": SYSTEM_REPORT_ID,
        "scope_type": "user",
        "user_id": TEST_USER_ID,
        "view_name": "My view",
        "criteria_json": '{"version": 1, "status": "active"}',
        "layout_json": '{"version": 1, "columns": [], "sort": [], "group": [], "aggregates": []}',
        "is_default": False,
        **_audit_fields(),
    }
    base.update(kwargs)
    return ReportSavedView(**base)  # type: ignore[arg-type]


def minimal_criteria(**kwargs: object) -> ReportCriteria:
    base: dict[str, object] = {
        "id": "01JRPT0CR00000000000000001",
        "report_id": SYSTEM_REPORT_ID,
        "criteria_key": "account_type",
        "display_name": "Account Type",
        "data_type": "string",
        "control_type": "multiselect",
        "lookup_proc": "rpt.usp_lookup_account_type",
        "default_value": None,
        "is_required": False,
        "display_order": 10,
        **_audit_fields(),
    }
    base.update(kwargs)
    return ReportCriteria(**base)  # type: ignore[arg-type]
