"""ReportCatalogService — key resolution, tenant isolation, response shape (mocked session)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import mssql

from mtf.rpt.services import ReportCatalogService
from tests.rpt.conftest import (
    OTHER_TENANT_ID,
    TENANT_REPORT_ID,
    TEST_TENANT_ID,
    minimal_column,
    minimal_criteria,
    minimal_report,
)


def _db_returning_first(*rows: object) -> MagicMock:
    """Each ``db.scalars(...)`` call returns the next row from ``.first()``."""
    db = MagicMock()
    results = []
    for row in rows:
        result = MagicMock()
        result.first.return_value = row
        results.append(result)
    db.scalars.side_effect = results
    return db


def _params(stmt: object) -> dict[str, object]:
    return stmt.compile(dialect=mssql.dialect()).params  # type: ignore[attr-defined]


def _stmt_sql(stmt: object) -> str:
    return str(stmt.compile(dialect=mssql.dialect()))  # type: ignore[attr-defined]


def test_resolve_prefers_tenant_report_over_system_report() -> None:
    tenant_report = minimal_report(
        id=TENANT_REPORT_ID,
        scope_type="tenant",
        tenant_id=TEST_TENANT_ID,
    )
    db = _db_returning_first(tenant_report)

    result = ReportCatalogService(db)._resolve_report(TEST_TENANT_ID, "tenant_account_list")

    assert result is tenant_report
    assert db.scalars.call_count == 1
    params = _params(db.scalars.call_args.args[0])
    assert TEST_TENANT_ID in params.values()
    assert "tenant" in params.values()


def test_resolve_falls_back_to_system_report() -> None:
    system_report = minimal_report()
    db = _db_returning_first(None, system_report)

    result = ReportCatalogService(db)._resolve_report(TEST_TENANT_ID, "tenant_account_list")

    assert result is system_report
    assert db.scalars.call_count == 2
    system_params = _params(db.scalars.call_args_list[1].args[0])
    assert "system" in system_params.values()
    assert TEST_TENANT_ID not in system_params.values()


def test_resolve_raises_404_when_no_visible_report() -> None:
    db = _db_returning_first(None, None)

    with pytest.raises(HTTPException) as exc_info:
        ReportCatalogService(db)._resolve_report(TEST_TENANT_ID, "missing")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "REPORT_NOT_FOUND"


def test_resolve_tenant_lookup_is_scoped_to_caller_tenant() -> None:
    """Another tenant's report can only be found by its own tenant_id, never by the caller's."""
    db = _db_returning_first(None, None)

    with pytest.raises(HTTPException):
        ReportCatalogService(db)._resolve_report(TEST_TENANT_ID, "other_tenant_report")

    tenant_params = _params(db.scalars.call_args_list[0].args[0])
    assert TEST_TENANT_ID in tenant_params.values()
    assert OTHER_TENANT_ID not in tenant_params.values()


def test_resolve_filters_soft_deleted_and_inactive() -> None:
    db = _db_returning_first(None, None)

    with pytest.raises(HTTPException):
        ReportCatalogService(db)._resolve_report(TEST_TENANT_ID, "x")

    for call in db.scalars.call_args_list:
        sql = _stmt_sql(call.args[0])
        assert "is_deleted" in sql
        assert "is_active" in sql


def test_list_reports_scopes_to_tenant_and_hides_overridden_system_reports() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = [minimal_report()]

    result = ReportCatalogService(db).list_reports(TEST_TENANT_ID)

    assert [r.report_key for r in result] == ["tenant_account_list"]
    stmt = db.scalars.call_args.args[0]
    sql = _stmt_sql(stmt)
    params = _params(stmt)
    assert "EXISTS" in sql
    assert "ORDER BY" in sql
    assert "OFFSET" not in sql
    assert "FETCH" not in sql
    assert "TOP" not in sql
    assert TEST_TENANT_ID in params.values()
    assert OTHER_TENANT_ID not in params.values()
    assert "system" in params.values()


def test_get_lookup_criteria_returns_lookup_criterion() -> None:
    criterion = minimal_criteria()
    db = _db_returning_first(None, minimal_report(), criterion)

    result = ReportCatalogService(db).get_lookup_criteria(
        TEST_TENANT_ID, "tenant_account_list", "account_type"
    )

    assert result is criterion
    params = _params(db.scalars.call_args_list[2].args[0])
    assert "account_type" in params.values()
    assert minimal_report().id in params.values()


@pytest.mark.parametrize(
    "criterion",
    [
        None,
        minimal_criteria(control_type="daterange", data_type="date", lookup_proc=None),
        minimal_criteria(control_type="text", lookup_proc="rpt.usp_lookup_account_type"),
        minimal_criteria(control_type="dropdown", lookup_proc=None),
        minimal_criteria(control_type="multiselect", lookup_proc=""),
    ],
)
def test_get_lookup_criteria_404_when_not_a_lookup(criterion: object) -> None:
    db = _db_returning_first(None, minimal_report(), criterion)

    with pytest.raises(HTTPException) as exc_info:
        ReportCatalogService(db).get_lookup_criteria(TEST_TENANT_ID, "tenant_account_list", "x")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "REPORT_LOOKUP_NOT_FOUND"


def test_get_lookup_criteria_report_not_found_is_report_404() -> None:
    db = _db_returning_first(None, None)

    with pytest.raises(HTTPException) as exc_info:
        ReportCatalogService(db).get_lookup_criteria(TEST_TENANT_ID, "missing", "x")

    assert exc_info.value.detail["code"] == "REPORT_NOT_FOUND"


def test_get_report_builds_detail_without_proc_names() -> None:
    db = MagicMock()
    resolve_result = MagicMock()
    resolve_result.first.side_effect = [None, minimal_report()]
    columns_result = MagicMock()
    columns_result.all.return_value = [minimal_column()]
    criteria_result = MagicMock()
    criteria_result.all.return_value = [
        minimal_criteria(),
        minimal_criteria(
            id="01JRPT0CR00000000000000003",
            criteria_key="created_date",
            display_name="Created Date",
            data_type="date",
            control_type="daterange",
            lookup_proc=None,
            display_order=30,
        ),
    ]
    db.scalars.side_effect = [resolve_result, resolve_result, columns_result, criteria_result]

    detail = ReportCatalogService(db).get_report(TEST_TENANT_ID, "tenant_account_list")

    assert detail.report_key == "tenant_account_list"
    assert detail.default_max_rows == 20000
    assert [c.column_name for c in detail.columns] == ["name"]
    assert [(c.criteria_key, c.has_lookup) for c in detail.criteria] == [
        ("account_type", True),
        ("created_date", False),
    ]
    dumped = detail.model_dump_json()
    assert "proc_name" not in dumped
    assert "lookup_proc" not in dumped
    assert "usp_" not in dumped
