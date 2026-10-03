"""End-to-end check of the five framework sample reports (docs/rpt_seed_sample_report.sql).

For each report: resolve it through the catalog, validate representative criteria, build
``@CriteriaJson``, run the proc on a session-context connection, and check the output
contract and that filters actually apply. Every lookup proc is exercised the same way.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from mtf.rpt.execution import LOOKUP_COLUMNS, execute_proc, open_report_connection
from mtf.rpt.services import ReportCatalogService, criteria_to_json, validate_report_criteria
from mtf.shared.database import SessionLocal, engine
from mtf.tenant.models import TenantAccount
from tests.rpt.conftest import OTHER_TENANT_ID, TEST_USER_ID

pytestmark = pytest.mark.integration

_FAR_PAST = "2000-01-01"
_FAR_FUTURE = "2100-12-31"
_ALL_ACCOUNT_TYPES = ["customer", "vendor", "employee"]
_ALL_STAFF_ROLES = ["owner", "admin", "member", "viewer"]

SAMPLE_CRITERIA: dict[str, dict[str, Any]] = {
    "tenant_account_list": {
        "account_type": _ALL_ACCOUNT_TYPES,
        "status": "active",
        "created_date": {"from": _FAR_PAST, "to": _FAR_FUTURE},
    },
    "tenant_account_summary": {
        "account_type": _ALL_ACCOUNT_TYPES,
        "created_date": {"from": _FAR_PAST},
    },
    "tenant_account_address_list": {
        "address_type": ["billing", "shipping"],
        "city": "a",
        "country": "US",
        "default_only": True,
    },
    "tenant_user_list": {
        "role": _ALL_STAFF_ROLES,
        "is_active": True,
        "joined_date": {"to": _FAR_FUTURE},
    },
    "portal_user_list": {"role": "admin", "is_active": True},
}


@pytest.fixture(scope="module")
def db() -> Generator[Session, None, None]:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    session = SessionLocal()
    try:
        session.execute(select(1))
    except DBAPIError as exc:
        session.close()
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    yield session
    session.close()


@pytest.fixture(scope="module")
def tenant_id(db: Session) -> str:
    found = db.scalars(
        select(TenantAccount.tenant_id).where(TenantAccount.is_deleted == False)  # noqa: E712
    ).first()
    if found is None:
        pytest.skip("no tenant accounts to report on")
    return found


def _load(db: Session, tenant_id: str, report_key: str):
    service = ReportCatalogService(db)
    try:
        report = service._resolve_report(tenant_id, report_key)
    except HTTPException:
        pytest.skip(f"{report_key} not seeded")
    return report, service._list_columns(report.id), service._list_criteria(report.id)


def _run(conn: Any, report: Any, columns: list[Any], criteria: dict[str, Any]):
    return execute_proc(
        conn,
        report.proc_name,
        [("@CriteriaJson", criteria_to_json(criteria))],
        max_rows=report.default_max_rows,
        expected_columns=[c.column_name for c in columns],
    )


def _rows_as_dicts(result: Any) -> list[dict[str, Any]]:
    return [dict(zip(result.columns, row, strict=True)) for row in result.rows]


@pytest.mark.parametrize("report_key", list(SAMPLE_CRITERIA))
def test_report_runs_unfiltered_and_filtered(db: Session, tenant_id: str, report_key: str) -> None:
    report, columns, criteria_specs = _load(db, tenant_id, report_key)
    raw = dict(SAMPLE_CRITERIA[report_key])

    with open_report_connection(tenant_id, TEST_USER_ID) as conn:
        if any(c.criteria_key == "account_id" for c in criteria_specs):
            accounts = execute_proc(
                conn, "rpt.usp_lookup_account", [("@SearchText", None), ("@Values", None)],
                max_rows=1, expected_columns=LOOKUP_COLUMNS,
            )
            if accounts.rows:
                raw["account_id"] = accounts.rows[0][0]

        normalized = validate_report_criteria(raw, criteria_specs)
        assert set(normalized) == set(raw)

        unfiltered = _run(conn, report, columns, validate_report_criteria({}, criteria_specs))
        filtered = _run(conn, report, columns, normalized)

    assert unfiltered.truncated is False
    assert len(filtered.rows) <= len(unfiltered.rows)

    rows = _rows_as_dicts(filtered)
    if report_key == "tenant_account_list":
        assert all(r["status"] == "active" for r in rows)
        assert all(r["account_type"] in _ALL_ACCOUNT_TYPES for r in rows)
    elif report_key == "tenant_user_list":
        assert all(r["is_active"] is True and r["role"] in _ALL_STAFF_ROLES for r in rows)
    elif report_key == "portal_user_list":
        assert all(r["role"] == "admin" and r["is_active"] is True for r in rows)
    elif report_key == "tenant_account_address_list":
        assert all(r["is_default"] is True and r["country"] == "US" for r in rows)


@pytest.mark.parametrize("report_key", list(SAMPLE_CRITERIA))
def test_report_lookups_honour_contract_values_and_search(
    db: Session, tenant_id: str, report_key: str
) -> None:
    _, _, criteria_specs = _load(db, tenant_id, report_key)
    lookups = [c for c in criteria_specs if c.lookup_proc]

    with open_report_connection(tenant_id, TEST_USER_ID) as conn:
        for spec in lookups:
            everything = execute_proc(
                conn, spec.lookup_proc, [("@SearchText", None), ("@Values", None)],
                max_rows=200, expected_columns=LOOKUP_COLUMNS,
            )
            assert everything.columns == ["value", "label"], spec.lookup_proc
            assert all(isinstance(v, str) for v, _ in everything.rows), spec.lookup_proc
            if not everything.rows:
                continue

            value, label = everything.rows[0]
            by_value = execute_proc(
                conn, spec.lookup_proc, [("@SearchText", None), ("@Values", f'["{value}"]')],
                max_rows=200, expected_columns=LOOKUP_COLUMNS,
            )
            assert [v for v, _ in by_value.rows] == [value], spec.lookup_proc

            by_search = execute_proc(
                conn, spec.lookup_proc, [("@SearchText", label[:3]), ("@Values", None)],
                max_rows=200, expected_columns=LOOKUP_COLUMNS,
            )
            assert value in [v for v, _ in by_search.rows], spec.lookup_proc

            # every lookup value must pass the validator for its own criterion
            raw = [value] if spec.control_type == "multiselect" else value
            validate_report_criteria({spec.criteria_key: raw}, [spec])


def test_other_tenant_sees_none_of_this_tenants_rows(db: Session, tenant_id: str) -> None:
    report, columns, _ = _load(db, tenant_id, "tenant_account_list")
    with open_report_connection(tenant_id, TEST_USER_ID) as conn:
        mine = _run(conn, report, columns, {})
    with open_report_connection(OTHER_TENANT_ID, TEST_USER_ID) as conn:
        theirs = _run(conn, report, columns, {})
    assert len(mine.rows) > 0
    assert theirs.rows == []


def test_proc_without_session_context_fails_as_500(db: Session, tenant_id: str) -> None:
    report, columns, _ = _load(db, tenant_id, "tenant_account_list")
    pooled = engine.raw_connection()
    try:
        with pytest.raises(HTTPException) as exc_info:
            _run(pooled.driver_connection, report, columns, {})
    finally:
        pooled.close()
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "REPORT_EXECUTION_FAILED"
