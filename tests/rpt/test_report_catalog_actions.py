"""Report catalog actions — visibility, target keys, no internal ids (mocked session)."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.dialects import mssql

from mtf.rpt.services import ReportCatalogService
from tests.rpt.conftest import (
    SAMPLE_ACTION_ID,
    SAMPLE_SCREEN_ID,
    SYSTEM_REPORT_ID,
    TARGET_REPORT_ID,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_action,
    minimal_action_param,
    minimal_report,
)
from tests.txn.conftest import SAMPLE_SCREEN_KEY, minimal_screen


def _stmt_sql(stmt: object) -> str:
    return str(stmt.compile(dialect=mssql.dialect()))


def _action_db(
    *,
    actions: list[object],
    params: list[object] | None = None,
    screens: list[object] | None = None,
    permission: object | None = None,
    report_first: list[object] | None = None,
) -> MagicMock:
    """Dispatch ``scalars()`` by compiled table name so action tests stay order-light."""
    params = params if params is not None else []
    screens = screens if screens is not None else []
    report_rows = iter(report_first or [])

    def scalars(stmt: object) -> MagicMock:
        sql = _stmt_sql(stmt).lower()
        result = MagicMock()
        if "report_action_param" in sql:
            result.all.return_value = params
        elif "report_action" in sql:
            result.all.return_value = actions
        elif "screen_permission" in sql:
            result.first.return_value = permission
        elif "txn.screen" in sql:
            result.all.return_value = screens
            result.first.return_value = screens[0] if screens else None
        elif "report_definition" in sql:
            result.first.return_value = next(report_rows, None)
        else:
            result.all.return_value = []
            result.first.return_value = None
        return result

    db = MagicMock()
    db.scalars.side_effect = scalars
    return db


def test_list_actions_filters_live_and_orders() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = []

    ReportCatalogService(db)._list_actions(SYSTEM_REPORT_ID)

    sql = _stmt_sql(db.scalars.call_args.args[0])
    params = db.scalars.call_args.args[0].compile(dialect=mssql.dialect()).params
    assert "is_deleted" in sql
    assert "is_active" in sql
    assert "display_order" in sql
    assert SYSTEM_REPORT_ID in params.values()


def test_screen_view_action_is_included_for_open_screen() -> None:
    action = minimal_action()
    param = minimal_action_param()
    db = _action_db(actions=[action], params=[param], screens=[minimal_screen()], permission=None)

    result = ReportCatalogService(db)._actions_for(
        SYSTEM_REPORT_ID, TEST_TENANT_ID, TEST_USER_ID
    )

    assert [a.action_key for a in result] == ["open_sample"]
    assert result[0].screen_key == SAMPLE_SCREEN_KEY
    assert result[0].screen_mode == "view"
    assert result[0].report_key is None
    assert result[0].display_location == "row"
    assert [(p.source_key, p.target_key) for p in result[0].params] == [("record_id", "id")]
    dumped = result[0].model_dump()
    assert SAMPLE_ACTION_ID not in str(dumped)
    assert SAMPLE_SCREEN_ID not in str(dumped)
    assert "target_screen_id" not in dumped
    assert "id" not in dumped


def test_screen_view_action_hidden_when_cannot_view() -> None:
    screen = minimal_screen(allow_view=False, allow_add=True)
    db = _action_db(actions=[minimal_action()], params=[], screens=[screen], permission=None)

    result = ReportCatalogService(db)._actions_for(
        SYSTEM_REPORT_ID, TEST_TENANT_ID, TEST_USER_ID
    )

    assert result == []


def test_screen_add_action_kept_for_add_only_user() -> None:
    action = minimal_action(
        action_key="add_sample",
        display_name="Add Sample",
        display_location="toolbar",
        screen_mode="add",
    )
    screen = minimal_screen(allow_view=False, allow_add=True)
    db = _action_db(actions=[action], params=[], screens=[screen], permission=None)

    result = ReportCatalogService(db)._actions_for(
        SYSTEM_REPORT_ID, TEST_TENANT_ID, TEST_USER_ID
    )

    assert [a.action_key for a in result] == ["add_sample"]
    assert result[0].screen_mode == "add"
    assert result[0].display_location == "toolbar"


def test_missing_target_screen_omits_action() -> None:
    db = _action_db(actions=[minimal_action()], params=[], screens=[], permission=None)

    result = ReportCatalogService(db)._actions_for(
        SYSTEM_REPORT_ID, TEST_TENANT_ID, TEST_USER_ID
    )

    assert result == []


def test_report_action_included_when_target_visible() -> None:
    target = minimal_report(id=TARGET_REPORT_ID, report_key="account_summary")
    action = minimal_action(
        action_key="drill_summary",
        display_name="Account Summary",
        action_type="report",
        display_location="row",
        target_screen_id=None,
        target_report_id=TARGET_REPORT_ID,
        screen_mode=None,
    )
    db = _action_db(
        actions=[action],
        params=[],
        screens=[],
        report_first=[target, None, target],
    )

    result = ReportCatalogService(db)._actions_for(
        SYSTEM_REPORT_ID, TEST_TENANT_ID, TEST_USER_ID
    )

    assert [a.action_key for a in result] == ["drill_summary"]
    assert result[0].report_key == "account_summary"
    assert result[0].screen_key is None
    assert result[0].screen_mode is None
    assert TARGET_REPORT_ID not in str(result[0].model_dump())


def test_report_action_omitted_when_target_not_visible() -> None:
    target = minimal_report(id=TARGET_REPORT_ID, report_key="hidden_report")
    action = minimal_action(
        action_key="drill_hidden",
        action_type="report",
        display_location="row",
        target_screen_id=None,
        target_report_id=TARGET_REPORT_ID,
        screen_mode=None,
    )
    db = _action_db(
        actions=[action],
        params=[],
        screens=[],
        report_first=[target, None, None],
    )

    result = ReportCatalogService(db)._actions_for(
        SYSTEM_REPORT_ID, TEST_TENANT_ID, TEST_USER_ID
    )

    assert result == []
