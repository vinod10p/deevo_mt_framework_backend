"""ReportRunService + encode_report_value (execute_proc patched, catalog mocked)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from mtf.rpt.execution import ProcResult
from mtf.rpt.services import ReportRunService, ResolvedReport, encode_report_value
from mtf.rpt.services import report_run as run_module
from tests.rpt.conftest import TEST_TENANT_ID, minimal_column, minimal_criteria, minimal_report

CONN = object()

# --- encode_report_value ---------------------------------------------------------


@pytest.mark.parametrize(
    ("data_type", "value", "expected"),
    [
        ("int", 7, 7),
        ("int", Decimal("7"), 7),
        ("decimal", Decimal("18400.50"), 18400.5),
        ("decimal", 3, 3.0),
        ("bool", True, True),
        ("bool", 0, False),
        ("date", date(2026, 3, 1), "2026-03-01"),
        ("date", datetime(2026, 3, 1, 10, 30), "2026-03-01"),
        ("datetime", datetime(2026, 3, 1, 10, 30, 5), "2026-03-01T10:30:05"),
        ("datetime", datetime(2026, 3, 1, 10, 30, 5, 123000), "2026-03-01T10:30:05.123000"),
        (
            "datetime",
            datetime(2026, 3, 1, 12, 0, tzinfo=timezone(timedelta(hours=2))),
            "2026-03-01T10:00:00",
        ),
        ("datetime", datetime(2026, 3, 1, 12, 0, tzinfo=UTC), "2026-03-01T12:00:00"),
        ("datetime", date(2026, 3, 1), "2026-03-01T00:00:00"),
        ("string", "Acme", "Acme"),
        ("string", 42, "42"),
        ("string", Decimal("1.50"), "1.50"),
    ],
)
def test_encode_report_value(data_type: str, value: Any, expected: Any) -> None:
    encoded = encode_report_value(data_type, value)
    assert encoded == expected
    assert type(encoded) is type(expected)


@pytest.mark.parametrize("data_type", ["string", "int", "decimal", "date", "datetime", "bool"])
def test_encode_null_is_none(data_type: str) -> None:
    assert encode_report_value(data_type, None) is None


# --- ReportRunService --------------------------------------------------------------


class Recorder(list):
    result = ProcResult(columns=["account_code", "name"], rows=[], truncated=False)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorded = Recorder()

    def fake_execute_proc(conn: Any, proc_name: str, params: Any, **kwargs: Any) -> ProcResult:
        recorded.append({"conn": conn, "proc_name": proc_name, "params": dict(params), **kwargs})
        return recorded.result

    monkeypatch.setattr(run_module, "execute_proc", fake_execute_proc)
    return recorded


def _resolved(**report_kwargs: Any) -> ResolvedReport:
    return ResolvedReport(
        definition=minimal_report(**report_kwargs),
        columns=[
            minimal_column(id="C1", column_name="account_code", display_order=10),
            minimal_column(id="C2", column_name="name", display_order=20),
            minimal_column(id="C3", column_name="is_active", data_type="bool", display_order=30),
            minimal_column(
                id="C4", column_name="created_at", data_type="datetime", display_order=40
            ),
        ],
        criteria=[
            minimal_criteria(),
            minimal_criteria(
                id="R2", criteria_key="created_date", data_type="date",
                control_type="daterange", lookup_proc=None,
            ),
        ],
    )


def _service(resolved: ResolvedReport | None = None) -> tuple[ReportRunService, MagicMock]:
    service = ReportRunService(MagicMock())
    catalog = MagicMock()
    catalog.resolve.return_value = resolved or _resolved()
    service._catalog = catalog
    return service, catalog


def test_run_binds_normalized_criteria_and_default_max_rows(calls: Recorder) -> None:
    calls.result = ProcResult(
        columns=["created_at", "is_active", "name", "account_code"], rows=[], truncated=False
    )
    service, catalog = _service()

    service.run(
        CONN, TEST_TENANT_ID, "tenant_account_list",
        criteria={"account_type": ["customer"], "created_date": {"from": "2026-01-01", "to": ""}},
    )

    catalog.resolve.assert_called_once_with(TEST_TENANT_ID, "tenant_account_list")
    call = calls[0]
    assert call["conn"] is CONN
    assert call["proc_name"] == "rpt.usp_tenant_account_list"
    assert call["params"] == {
        "@CriteriaJson": '{"account_type":["customer"],"created_date":{"from":"2026-01-01"}}'
    }
    assert call["max_rows"] == 20000
    assert list(call["expected_columns"]) == ["account_code", "name", "is_active", "created_at"]


@pytest.mark.parametrize(("requested", "expected"), [(100, 100), (0, 1), (10**9, 500)])
def test_run_clamps_max_rows_to_report_cap(
    calls: Recorder, requested: int, expected: int
) -> None:
    calls.result = ProcResult(
        columns=["account_code", "name", "is_active", "created_at"], rows=[], truncated=False
    )
    service, _ = _service(_resolved(default_max_rows=500))
    service.run(CONN, TEST_TENANT_ID, "r", max_rows=requested)
    assert calls[0]["max_rows"] == expected


def test_run_invalid_criteria_never_executes(calls: Recorder) -> None:
    service, _ = _service()
    with pytest.raises(HTTPException) as exc_info:
        service.run(CONN, TEST_TENANT_ID, "r", criteria={"tenant_id": "x", "account_type": "a"})
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "REPORT_CRITERIA_INVALID"
    assert set(exc_info.value.detail["fields"]) == {"tenant_id", "account_type"}
    assert calls == []


def test_run_maps_rows_by_column_name_and_encodes(calls: Recorder) -> None:
    calls.result = ProcResult(
        columns=["created_at", "is_active", "name", "account_code"],
        rows=[
            (datetime(2026, 3, 1, 9, 0), True, "Acme", "A001"),
            (None, False, "Beta", "B002"),
        ],
        truncated=True,
    )
    service, _ = _service()

    result = service.run(CONN, TEST_TENANT_ID, "tenant_account_list")

    assert result.report_key == "tenant_account_list"
    assert result.row_count == 2
    assert result.truncated is True
    assert result.rows == [
        {"account_code": "A001", "name": "Acme", "is_active": True,
         "created_at": "2026-03-01T09:00:00"},
        {"account_code": "B002", "name": "Beta", "is_active": False, "created_at": None},
    ]
    assert list(result.rows[0]) == ["account_code", "name", "is_active", "created_at"]


def test_run_value_not_matching_data_type_is_500(calls: Recorder) -> None:
    calls.result = ProcResult(
        columns=["account_code", "name", "is_active", "created_at"],
        rows=[("A001", "Acme", True, "not a date")],
        truncated=False,
    )
    service, _ = _service()
    with pytest.raises(HTTPException) as exc_info:
        service.run(CONN, TEST_TENANT_ID, "r")
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "REPORT_EXECUTION_FAILED"
    assert "not a date" not in str(exc_info.value.detail)
