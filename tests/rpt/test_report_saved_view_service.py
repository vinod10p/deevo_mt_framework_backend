"""ReportSavedViewService read side — visibility filter, ordering, default precedence."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import mssql

from mtf.rpt.services import ReportSavedViewService
from tests.rpt.conftest import (
    OTHER_TENANT_ID,
    SYSTEM_REPORT_ID,
    TENANT_REPORT_ID,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_report,
    minimal_saved_view,
    tenant_user,
)


def _service(
    views: list, *, report=None, can_edit: bool = True
) -> tuple[ReportSavedViewService, MagicMock]:
    db = MagicMock()
    db.scalars.return_value.all.return_value = views
    service = ReportSavedViewService(db)
    service._catalog = MagicMock()
    service._catalog.resolve_definition.return_value = report or minimal_report()
    service._authorizer = MagicMock()
    service._authorizer.can_edit.return_value = can_edit
    return service, db


def _compiled(db: MagicMock) -> tuple[str, dict]:
    stmt = db.scalars.call_args.args[0]
    compiled = stmt.compile(dialect=mssql.dialect())
    return str(compiled), compiled.params


def test_list_resolves_report_with_jwt_tenant() -> None:
    service, _ = _service([])
    service.list_views(tenant_user(), "tenant_account_list")
    service._catalog.resolve_definition.assert_called_once_with(
        TEST_TENANT_ID, "tenant_account_list"
    )


def test_list_filter_scopes_to_caller_tenant_and_own_user_views() -> None:
    service, db = _service([])
    service.list_views(tenant_user(), "tenant_account_list")
    sql, params = _compiled(db)

    assert SYSTEM_REPORT_ID in params.values()
    assert TEST_TENANT_ID in params.values()
    assert TEST_USER_ID in params.values()
    assert OTHER_TENANT_ID not in params.values()
    assert {"user", "tenant", "system"} <= set(params.values())
    assert "is_deleted" in sql and "is_active" in sql
    assert "tenant_id IS NULL" in sql
    assert "ORDER BY CASE" in sql


def test_system_tier_excluded_for_tenant_owned_report() -> None:
    tenant_report = minimal_report(
        id=TENANT_REPORT_ID, scope_type="tenant", tenant_id=TEST_TENANT_ID
    )
    service, db = _service([], report=tenant_report)
    service.list_views(tenant_user(), "custom")
    sql, params = _compiled(db)
    scope_filters = [v for k, v in params.items() if k.startswith("scope_type")]
    assert sorted(scope_filters) == ["tenant", "user"]
    assert "tenant_id IS NULL" not in sql


def test_list_maps_rows_and_strips_version() -> None:
    view = minimal_saved_view(
        criteria_json='{"version": 1, "status": "active", "created_date": {"from": "2026-01-01"}}',
        layout_json='{"version": 1, "group": ["account_type"]}',
    )
    service, _ = _service([view], can_edit=True)

    [result] = service.list_views(tenant_user(), "tenant_account_list")

    assert result.id == view.id
    assert result.scope_type == "user"
    assert result.can_edit is True
    assert result.criteria == {"status": "active", "created_date": {"from": "2026-01-01"}}
    assert result.layout == {"columns": [], "sort": [], "group": ["account_type"], "aggregates": []}
    assert result.row_version == view.row_version
    service._authorizer.can_edit.assert_called_once()


def test_row_version_serialized_as_base64() -> None:
    service, _ = _service([minimal_saved_view()])
    [result] = service.list_views(tenant_user(), "r")
    assert '"row_version":"AAECAwQFBgc="' in result.model_dump_json()


@pytest.mark.parametrize(
    ("scopes", "expected"),
    [
        (["system", "tenant", "user"], "user"),
        (["system", "tenant"], "tenant"),
        (["tenant", "system"], "tenant"),
        (["system"], "system"),
    ],
)
def test_default_precedence_user_tenant_system(scopes: list[str], expected: str) -> None:
    views = [
        minimal_saved_view(id=f"V{scope}", scope_type=scope, is_default=True,
                           user_id=TEST_USER_ID if scope == "user" else None,
                           tenant_id=None if scope == "system" else TEST_TENANT_ID)
        for scope in scopes
    ]
    service, db = _service(views)

    result = service.get_default_view(tenant_user(), "tenant_account_list")

    assert result is not None and result.scope_type == expected
    sql, _ = _compiled(db)
    assert "is_default = 1" in sql


def test_default_none_when_no_defaults() -> None:
    service, _ = _service([])
    assert service.get_default_view(tenant_user(), "tenant_account_list") is None
