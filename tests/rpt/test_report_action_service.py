"""ReportActionService.resolve — generic mapping and target checks (mocked collaborators)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from mtf.rpt.services import ResolvedReport, map_action_sources
from mtf.rpt.services.report_action import ReportActionService
from mtf.txn.services.screen_permission import resolve_screen_permissions
from tests.rpt.conftest import (
    SAMPLE_ACTION_ID,
    TARGET_REPORT_ID,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_action,
    minimal_action_param,
    minimal_criteria,
    minimal_report,
)
from tests.txn.conftest import SAMPLE_SCREEN_KEY, minimal_screen


def _service(
    *,
    action: object | None = None,
    params: list[object] | None = None,
    screen: object | None = None,
    perms_screen: object | None = None,
    target_report_key: str | None = "account_summary",
    target_criteria: list[object] | None = None,
) -> ReportActionService:
    catalog = MagicMock()
    catalog.resolve_definition.return_value = minimal_report()
    catalog.get_live_action.return_value = action if action is not None else minimal_action()
    catalog.list_live_action_params.return_value = (
        params if params is not None else [minimal_action_param()]
    )
    catalog.live_screen.return_value = screen if screen is not None else minimal_screen()
    catalog.visible_target_report_key.return_value = target_report_key
    catalog.resolve.return_value = ResolvedReport(
        definition=minimal_report(id=TARGET_REPORT_ID, report_key="account_summary"),
        columns=[],
        criteria=target_criteria
        if target_criteria is not None
        else [
            minimal_criteria(
                criteria_key="account_code",
                display_name="Account Code",
                control_type="text",
                lookup_proc=None,
            )
        ],
    )
    screens = MagicMock()
    screens.resolve_for_screen.return_value = resolve_screen_permissions(
        perms_screen if perms_screen is not None else minimal_screen(),
        None,
    )
    return ReportActionService(MagicMock(), catalog=catalog, screens=screens)


def test_map_copies_declared_sources_only() -> None:
    params = [
        minimal_action_param(),
        minimal_action_param(
            id="01JRPT0AP00000000000000002",
            source_type="criteria",
            source_key="status",
            target_key="status",
        ),
    ]

    mapped = map_action_sources(
        params,
        {"record_id": "01JSAMPLE0000000000000001", "extra": "ignored"},
        {"status": "open", "other": "ignored"},
    )

    assert mapped == {"id": "01JSAMPLE0000000000000001", "status": "open"}


def test_map_requires_declared_sources() -> None:
    with pytest.raises(HTTPException) as exc_info:
        map_action_sources([minimal_action_param()], {}, {})

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "REPORT_ACTION_INVALID"
    assert exc_info.value.detail["fields"]["record_id"] == "Required"


def test_resolve_screen_view_maps_row_to_params() -> None:
    result = _service().resolve(
        TEST_TENANT_ID,
        TEST_USER_ID,
        "tenant_account_list",
        "open_sample",
        row={"record_id": "01JSAMPLE0000000000000001", "name": "ignored"},
        criteria={},
    )

    assert result.target_type == "screen"
    assert result.screen_key == SAMPLE_SCREEN_KEY
    assert result.mode == "view"
    assert result.params == {"id": "01JSAMPLE0000000000000001"}
    assert SAMPLE_ACTION_ID not in str(result.model_dump())


def test_resolve_toolbar_add_with_no_params() -> None:
    action = minimal_action(
        action_key="add_sample",
        display_location="toolbar",
        screen_mode="add",
    )
    result = _service(action=action, params=[]).resolve(
        TEST_TENANT_ID,
        TEST_USER_ID,
        "tenant_account_list",
        "add_sample",
        row={},
        criteria={},
    )

    assert result.target_type == "screen"
    assert result.mode == "add"
    assert result.params == {}


def test_resolve_screen_forbidden_when_cannot_view() -> None:
    svc = _service(perms_screen=minimal_screen(allow_view=False, allow_add=True))

    with pytest.raises(HTTPException) as exc_info:
        svc.resolve(
            TEST_TENANT_ID,
            TEST_USER_ID,
            "tenant_account_list",
            "open_sample",
            row={"record_id": "01JSAMPLE0000000000000001"},
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "SCREEN_FORBIDDEN"


def test_resolve_missing_target_screen_is_action_404() -> None:
    catalog = MagicMock()
    catalog.resolve_definition.return_value = minimal_report()
    catalog.get_live_action.return_value = minimal_action()
    catalog.list_live_action_params.return_value = [minimal_action_param()]
    catalog.live_screen.return_value = None
    svc = ReportActionService(MagicMock(), catalog=catalog, screens=MagicMock())

    with pytest.raises(HTTPException) as exc_info:
        svc.resolve(
            TEST_TENANT_ID,
            TEST_USER_ID,
            "tenant_account_list",
            "open_sample",
            row={"record_id": "01JSAMPLE0000000000000001"},
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "REPORT_ACTION_NOT_FOUND"


def test_resolve_report_maps_to_target_criteria() -> None:
    action = minimal_action(
        action_key="drill_summary",
        action_type="report",
        display_location="row",
        target_screen_id=None,
        target_report_id=TARGET_REPORT_ID,
        screen_mode=None,
    )
    param = minimal_action_param(source_key="account_code", target_key="account_code")
    result = _service(action=action, params=[param]).resolve(
        TEST_TENANT_ID,
        TEST_USER_ID,
        "tenant_account_list",
        "drill_summary",
        row={"account_code": "A100"},
    )

    assert result.target_type == "report"
    assert result.report_key == "account_summary"
    assert result.criteria == {"account_code": "A100"}
    assert TARGET_REPORT_ID not in str(result.model_dump())


def test_resolve_report_hidden_target_is_report_404() -> None:
    action = minimal_action(
        action_key="drill_hidden",
        action_type="report",
        target_screen_id=None,
        target_report_id=TARGET_REPORT_ID,
        screen_mode=None,
    )
    svc = _service(action=action, params=[], target_report_key=None)

    with pytest.raises(HTTPException) as exc_info:
        svc.resolve(TEST_TENANT_ID, TEST_USER_ID, "tenant_account_list", "drill_hidden")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "REPORT_NOT_FOUND"
