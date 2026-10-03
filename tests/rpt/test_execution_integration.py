"""Execution infrastructure integration tests (live SQL Server + docs/rpt_seed_sample_report.sql).

Runs seeded report and lookup procs through ``open_report_connection`` + ``execute_proc``
and checks session context is cleared before the connection is reused.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import DBAPIError

from mtf.rpt.execution import execute_proc, open_report_connection
from mtf.rpt.models import ReportColumn, ReportDefinition
from mtf.rpt.services import criteria_to_json
from mtf.shared.config import get_settings
from mtf.shared.database import SessionLocal
from mtf.tenant.models import TenantAccount
from tests.rpt.conftest import TEST_USER_ID

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def seeded() -> dict[str, object]:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    try:
        with SessionLocal() as db:
            report = db.scalars(
                select(ReportDefinition).where(
                    ReportDefinition.report_key == "tenant_account_list",
                    ReportDefinition.scope_type == "system",
                    ReportDefinition.is_deleted == False,  # noqa: E712
                )
            ).first()
            tenant_id = db.scalars(
                select(TenantAccount.tenant_id).where(TenantAccount.is_deleted == False)  # noqa: E712
            ).first()
            if report is None or tenant_id is None:
                pytest.skip("rpt sample reports or tenant accounts not seeded")
            columns = db.scalars(
                select(ReportColumn.column_name).where(
                    ReportColumn.report_id == report.id,
                    ReportColumn.is_deleted == False,  # noqa: E712
                    ReportColumn.is_active == True,  # noqa: E712
                )
            ).all()
            return {"proc": report.proc_name, "columns": list(columns), "tenant_id": tenant_id}
    except DBAPIError as exc:
        pytest.skip(f"rpt schema not available: {exc.__class__.__name__}")


@pytest.fixture
def single_conn_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        get_settings().sqlalchemy_database_uri(), pool_size=1, max_overflow=0
    )
    yield engine
    engine.dispose()


def test_report_proc_runs_with_session_context(seeded: dict[str, object]) -> None:
    with open_report_connection(seeded["tenant_id"], TEST_USER_ID) as conn:  # type: ignore[arg-type]
        result = execute_proc(
            conn,
            seeded["proc"],  # type: ignore[arg-type]
            [("@CriteriaJson", criteria_to_json({}))],
            max_rows=5,
            expected_columns=seeded["columns"],  # type: ignore[arg-type]
        )
    assert sorted(result.columns) == sorted(seeded["columns"])  # type: ignore[arg-type]
    assert len(result.rows) <= 5


def test_report_proc_truncation_with_max_rows_one(seeded: dict[str, object]) -> None:
    with open_report_connection(seeded["tenant_id"], TEST_USER_ID) as conn:  # type: ignore[arg-type]
        full = execute_proc(
            conn, "rpt.usp_lookup_tenant_user_role",
            [("@SearchText", None), ("@Values", None)],
            max_rows=50, expected_columns=["value", "label"],
        )
        one = execute_proc(
            conn, "rpt.usp_lookup_tenant_user_role",
            [("@SearchText", None), ("@Values", None)],
            max_rows=1, expected_columns=["value", "label"],
        )
    assert full.truncated is False and len(full.rows) == 4
    assert one.truncated is True and len(one.rows) == 1


def test_lookup_values_filter_bound_as_json(seeded: dict[str, object]) -> None:
    with open_report_connection(seeded["tenant_id"], TEST_USER_ID) as conn:  # type: ignore[arg-type]
        result = execute_proc(
            conn, "rpt.usp_lookup_tenant_user_role",
            [("@SearchText", None), ("@Values", '["admin","viewer"]')],
            max_rows=50, expected_columns=["value", "label"],
        )
    assert [row[0] for row in result.rows] == ["admin", "viewer"]


def test_session_context_cleared_before_reuse(
    seeded: dict[str, object], single_conn_engine: Engine
) -> None:
    sql = "SELECT CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26)), " \
          "CAST(SESSION_CONTEXT(N'user_id') AS varchar(26))"
    with open_report_connection(
        seeded["tenant_id"], TEST_USER_ID, engine=single_conn_engine  # type: ignore[arg-type]
    ) as conn:
        assert tuple(conn.cursor().execute(sql).fetchone()) == (seeded["tenant_id"], TEST_USER_ID)

    pooled = single_conn_engine.raw_connection()
    try:
        assert tuple(pooled.driver_connection.cursor().execute(sql).fetchone()) == (None, None)
    finally:
        pooled.close()
