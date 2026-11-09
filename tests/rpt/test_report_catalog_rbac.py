"""Catalog and resolve hide reports without role_report.can_view (404, not 403)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from mtf.auth.services.permission_resolver import ReportGrant
from mtf.rpt.services import ReportCatalogService
from tests.rpt.conftest import (
    SYSTEM_REPORT_ID,
    TEST_TENANT_ID,
    minimal_report,
    system_user,
    tenant_user,
)


def _granted(*report_ids: str) -> MagicMock:
    resolver = MagicMock()
    resolver.report_grants.return_value = {
        rid: ReportGrant(report_id=rid, can_view=True, can_export=False) for rid in report_ids
    }
    return resolver


def test_list_reports_without_user_does_not_filter_by_grants() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = [minimal_report()]
    result = ReportCatalogService(db).list_reports(TEST_TENANT_ID)
    assert [r.report_key for r in result] == ["tenant_account_list"]
    db.execute.assert_not_called()


def test_list_reports_empty_grants_returns_empty_without_catalog_query() -> None:
    db = MagicMock()
    result = ReportCatalogService(
        db,
        user=tenant_user(),
        resolver=_granted(),
    ).list_reports(TEST_TENANT_ID)
    assert result == []
    db.scalars.assert_not_called()


def test_list_reports_restricts_sql_to_viewable_ids() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = [minimal_report()]
    ReportCatalogService(
        db,
        user=tenant_user(),
        resolver=_granted(SYSTEM_REPORT_ID),
    ).list_reports(TEST_TENANT_ID)
    stmt = db.scalars.call_args.args[0]
    sql = str(stmt.compile()).lower()
    assert " in (" in sql or " in:" in sql
    assert SYSTEM_REPORT_ID in str(stmt.compile().params)


def test_resolve_granted_system_report() -> None:
    report = minimal_report()
    db = MagicMock()
    first = MagicMock()
    first.first.side_effect = [None, report]
    db.scalars.return_value = first
    found = ReportCatalogService(
        db,
        user=tenant_user(),
        resolver=_granted(SYSTEM_REPORT_ID),
    )._resolve_report(TEST_TENANT_ID, "tenant_account_list")
    assert found is report


def test_resolve_unauthorized_is_same_404_as_unknown() -> None:
    report = minimal_report()
    db = MagicMock()
    db.scalars.return_value.first.side_effect = [None, report]
    with pytest.raises(HTTPException) as hidden:
        ReportCatalogService(
            db,
            user=tenant_user(),
            resolver=_granted("01OTHERREPORT0000000000001"),
        )._resolve_report(TEST_TENANT_ID, "tenant_account_list")
    assert hidden.value.status_code == 404
    assert hidden.value.detail["code"] == "REPORT_NOT_FOUND"
    assert hidden.value.detail["message"] == "Report not found"


def test_system_user_skips_role_report_filter() -> None:
    db = MagicMock()
    db.scalars.return_value.all.return_value = [minimal_report()]
    resolver = MagicMock()
    ReportCatalogService(
        db,
        user=system_user(),
        resolver=resolver,
    ).list_reports(TEST_TENANT_ID)
    resolver.report_grants.assert_not_called()
