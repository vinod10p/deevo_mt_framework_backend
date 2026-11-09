"""Shared helpers — rpt tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime

import pytest

from mtf.rpt.models import (
    ReportAction,
    ReportActionParam,
    ReportColumn,
    ReportCriteria,
    ReportDefinition,
    ReportSavedView,
)
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
TARGET_REPORT_ID = "01JRPT0DF00000000000000003"
SAMPLE_ACTION_ID = "01JRPT0AC00000000000000001"
SAMPLE_ACTION_PARAM_ID = "01JRPT0AP00000000000000001"
SAMPLE_SCREEN_ID = "01JTXNSCR00000000000000001"


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


def live_tenant_staff(*, tenant_id: str | None = None) -> CurrentUser:
    """JWT identity for a live ``tenant_user`` row (needs backfilled ``user_role``)."""
    from sqlalchemy import select

    from mtf.auth.models.tenant_user import TenantUser
    from mtf.shared.database import SessionLocal

    with SessionLocal() as db:
        filters = [
            TenantUser.is_deleted == False,  # noqa: E712
            TenantUser.is_active == True,  # noqa: E712
        ]
        if tenant_id is not None:
            filters.append(TenantUser.tenant_id == tenant_id)
        row = db.scalars(select(TenantUser).where(*filters).limit(1)).first()
    if row is None:
        pytest.skip("no live tenant_user row")
    return CurrentUser(
        user_id=row.user_id,
        user_type="app_user",
        user_scope="tenant",
        tenant_id=row.tenant_id,
    )


def live_portal_user(*, tenant_id: str | None = None) -> CurrentUser:
    """JWT identity for a live ``tenant_account_user`` row."""
    from sqlalchemy import select

    from mtf.auth.models.tenant_account_user import TenantAccountUser
    from mtf.shared.database import SessionLocal

    with SessionLocal() as db:
        filters = [
            TenantAccountUser.is_deleted == False,  # noqa: E712
            TenantAccountUser.is_active == True,  # noqa: E712
        ]
        if tenant_id is not None:
            filters.append(TenantAccountUser.tenant_id == tenant_id)
        row = db.scalars(select(TenantAccountUser).where(*filters).limit(1)).first()
    if row is None:
        pytest.skip("no live tenant_account_user row")
    return CurrentUser(
        user_id=row.user_id,
        user_type="app_user",
        user_scope="tenant_account",
        tenant_id=row.tenant_id,
        account_id=row.account_id,
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


def minimal_action(**kwargs: object) -> ReportAction:
    base: dict[str, object] = {
        "id": SAMPLE_ACTION_ID,
        "report_id": SYSTEM_REPORT_ID,
        "action_key": "open_sample",
        "display_name": "Open Sample",
        "action_type": "screen",
        "display_location": "row",
        "trigger_column_key": None,
        "target_report_id": None,
        "target_screen_id": SAMPLE_SCREEN_ID,
        "screen_mode": "view",
        "display_order": 10,
        **_audit_fields(),
    }
    base.update(kwargs)
    return ReportAction(**base)  # type: ignore[arg-type]


def minimal_action_param(**kwargs: object) -> ReportActionParam:
    base: dict[str, object] = {
        "id": SAMPLE_ACTION_PARAM_ID,
        "action_id": SAMPLE_ACTION_ID,
        "source_type": "column",
        "source_key": "record_id",
        "target_key": "id",
        **_audit_fields(),
    }
    base.update(kwargs)
    return ReportActionParam(**base)  # type: ignore[arg-type]


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
