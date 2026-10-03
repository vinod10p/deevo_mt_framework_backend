"""Unit tests — rpt execution infrastructure (fake pyodbc connection, no DB)."""

from __future__ import annotations

from typing import Any

import pyodbc
import pytest
from fastapi import HTTPException

from mtf.rpt.execution import (
    EXECUTION_FAILED_MESSAGE,
    clamp_max_rows,
    execute_proc,
    open_report_connection,
    quote_proc_name,
)


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn
        self._sets: list[tuple[list[str] | None, list[tuple]]] = []
        self._index = 0
        self.closed = False

    def execute(self, sql: str, *params: Any) -> FakeCursor:
        self._conn.executed.append((sql, params, self._conn.timeout))
        if self._conn.error is not None and self._conn.error_on in sql:
            raise self._conn.error
        self._sets = list(self._conn.result_sets)
        self._index = 0
        return self

    @property
    def description(self) -> list[tuple] | None:
        if self._index >= len(self._sets) or self._sets[self._index][0] is None:
            return None
        return [(name, str, None, None, None, None, True) for name in self._sets[self._index][0]]

    def nextset(self) -> bool:
        self._index += 1
        return self._index < len(self._sets)

    def fetchmany(self, size: int) -> list[tuple]:
        self._conn.fetch_sizes.append(size)
        return self._sets[self._index][1][:size]

    def close(self) -> None:
        self.closed = True
        self._conn.cursors_closed += 1


class FakeConnection:
    def __init__(
        self,
        result_sets: list[tuple[list[str] | None, list[tuple]]] | None = None,
        *,
        error: Exception | None = None,
        error_on: str = "",
    ) -> None:
        self.result_sets = result_sets or []
        self.error = error
        self.error_on = error_on
        self.timeout = 0
        self.executed: list[tuple[str, tuple, int]] = []
        self.fetch_sizes: list[int] = []
        self.cursors_closed = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


class FakePooled:
    def __init__(self, conn: FakeConnection) -> None:
        self.driver_connection = conn
        self.closed = False
        self.invalidated = False

    def close(self) -> None:
        self.closed = True

    def invalidate(self) -> None:
        self.invalidated = True


class FakeEngine:
    def __init__(self, conn: FakeConnection) -> None:
        self.pooled = FakePooled(conn)

    def raw_connection(self) -> FakePooled:
        return self.pooled


def _assert_execution_failed(exc_info: pytest.ExceptionInfo[HTTPException]) -> None:
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == {
        "code": "REPORT_EXECUTION_FAILED",
        "message": EXECUTION_FAILED_MESSAGE,
    }


# --- quote_proc_name / clamp_max_rows ------------------------------------------


@pytest.mark.parametrize(
    ("name", "quoted"),
    [("rpt.usp_tenant_account_list", "[rpt].[usp_tenant_account_list]"), ("a._b1", "[a].[_b1]")],
)
def test_quote_proc_name_valid(name: str, quoted: str) -> None:
    assert quote_proc_name(name) == quoted


@pytest.mark.parametrize(
    "name",
    [
        "usp_no_schema",
        "db.rpt.usp_x",
        "rpt.usp_x; DROP TABLE t",
        "[rpt].[usp_x]",
        "rpt.usp x",
        "rpt.1usp",
        "",
    ],
)
def test_quote_proc_name_rejects_anything_else(name: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        quote_proc_name(name)
    _assert_execution_failed(exc_info)


@pytest.mark.parametrize(
    ("requested", "cap", "default", "expected"),
    [
        (None, 20000, None, 20000),
        (100, 20000, None, 100),
        (999999, 20000, None, 20000),
        (0, 20000, None, 1),
        (-5, 20000, None, 1),
        (None, 200, 50, 50),
        (500, 200, 50, 200),
    ],
)
def test_clamp_max_rows(
    requested: int | None, cap: int, default: int | None, expected: int
) -> None:
    assert clamp_max_rows(requested, cap=cap, default=default) == expected


# --- execute_proc ----------------------------------------------------------------


def test_execute_proc_binds_params_and_appends_max_rows() -> None:
    conn = FakeConnection([(["value", "label"], [("a", "A")])])
    execute_proc(
        conn,
        "rpt.usp_lookup_account",
        [("@SearchText", "o'brien"), ("@Values", None)],
        max_rows=50,
        expected_columns=["value", "label"],
        timeout_seconds=7,
    )
    sql, params, timeout = conn.executed[0]
    assert sql == (
        "SET NOCOUNT ON; EXEC [rpt].[usp_lookup_account] "
        "@SearchText = ?, @Values = ?, @MaxRows = ?"
    )
    assert params == ("o'brien", None, 50)
    assert timeout == 7
    assert conn.timeout == 0
    assert conn.cursors_closed == 1


def test_execute_proc_not_truncated_when_at_limit() -> None:
    rows = [(str(i), f"L{i}") for i in range(3)]
    conn = FakeConnection([(["value", "label"], rows)])
    result = execute_proc(
        conn, "rpt.usp_x", [], max_rows=3, expected_columns=["label", "value"], timeout_seconds=5
    )
    assert result.truncated is False
    assert result.rows == rows
    assert result.columns == ["value", "label"]
    assert conn.fetch_sizes == [4]


def test_execute_proc_trims_extra_row_and_flags_truncated() -> None:
    rows = [(str(i), f"L{i}") for i in range(10)]
    conn = FakeConnection([(["value", "label"], rows)])
    result = execute_proc(
        conn, "rpt.usp_x", [], max_rows=3, expected_columns=["value", "label"], timeout_seconds=5
    )
    assert result.truncated is True
    assert result.rows == rows[:3]


def test_execute_proc_skips_leading_rowcount_sets() -> None:
    conn = FakeConnection([(None, []), (["value", "label"], [("a", "A")])])
    result = execute_proc(
        conn, "rpt.usp_x", [], max_rows=5, expected_columns=["value", "label"], timeout_seconds=5
    )
    assert result.rows == [("a", "A")]


@pytest.mark.parametrize(
    "columns",
    [
        ["value"],
        ["value", "label", "extra"],
        ["value", "name"],
        ["value", "value", "label"],
    ],
)
def test_execute_proc_output_contract_mismatch(columns: list[str]) -> None:
    conn = FakeConnection([(columns, [])])
    with pytest.raises(HTTPException) as exc_info:
        execute_proc(
            conn, "rpt.usp_x", [],
            max_rows=5, expected_columns=["value", "label"], timeout_seconds=5,
        )
    _assert_execution_failed(exc_info)
    assert conn.timeout == 0


def test_execute_proc_no_result_set() -> None:
    conn = FakeConnection([(None, [])])
    with pytest.raises(HTTPException) as exc_info:
        execute_proc(conn, "rpt.usp_x", [], max_rows=5, expected_columns=["a"], timeout_seconds=5)
    _assert_execution_failed(exc_info)


def test_execute_proc_db_error_is_generic_500(caplog: pytest.LogCaptureFixture) -> None:
    conn = FakeConnection(
        error=pyodbc.ProgrammingError("42000", "Could not find stored procedure 'rpt.usp_x'"),
        error_on="EXEC",
    )
    with pytest.raises(HTTPException) as exc_info:
        execute_proc(conn, "rpt.usp_x", [], max_rows=5, expected_columns=["a"], timeout_seconds=5)
    _assert_execution_failed(exc_info)
    assert "usp_x" not in str(exc_info.value.detail)
    assert "rpt.usp_x failed" in caplog.text
    assert conn.timeout == 0
    assert conn.cursors_closed == 1


def test_execute_proc_timeout_logged_as_timeout(caplog: pytest.LogCaptureFixture) -> None:
    conn = FakeConnection(
        error=pyodbc.OperationalError("HYT00", "Query timeout expired"), error_on="EXEC"
    )
    with pytest.raises(HTTPException) as exc_info:
        execute_proc(conn, "rpt.usp_x", [], max_rows=5, expected_columns=["a"], timeout_seconds=9)
    _assert_execution_failed(exc_info)
    assert "timed out after 9s" in caplog.text


def test_execute_proc_rejects_bad_param_name() -> None:
    conn = FakeConnection([(["a"], [])])
    with pytest.raises(HTTPException) as exc_info:
        execute_proc(
            conn, "rpt.usp_x", [("@x; --", 1)],
            max_rows=5, expected_columns=["a"], timeout_seconds=5,
        )
    _assert_execution_failed(exc_info)
    assert conn.executed == []


def test_execute_proc_default_timeout_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from mtf.shared.config import get_settings

    monkeypatch.setattr(get_settings(), "report_query_timeout_seconds", 13)
    conn = FakeConnection([(["a"], [])])
    execute_proc(conn, "rpt.usp_x", [], max_rows=5, expected_columns=["a"])
    assert conn.executed[0][2] == 13


# --- open_report_connection --------------------------------------------------------


def test_open_report_connection_sets_and_clears_context() -> None:
    conn = FakeConnection()
    engine = FakeEngine(conn)
    with open_report_connection("T1", "U1", engine=engine) as yielded:  # type: ignore[arg-type]
        assert yielded is conn
        set_sql, set_params, _ = conn.executed[0]
        assert "@key = N'tenant_id', @value = ?" in set_sql
        assert "@key = N'user_id', @value = ?" in set_sql
        assert "read_only" not in set_sql
        assert set_params == ("T1", "U1")
    clear_sql, clear_params, _ = conn.executed[-1]
    assert "@key = N'tenant_id', @value = NULL" in clear_sql
    assert "@key = N'user_id', @value = NULL" in clear_sql
    assert clear_params == ()
    assert engine.pooled.closed is True
    assert engine.pooled.invalidated is False


def test_open_report_connection_clears_context_when_body_raises() -> None:
    conn = FakeConnection()
    engine = FakeEngine(conn)
    with pytest.raises(RuntimeError):
        with open_report_connection("T1", "U1", engine=engine):  # type: ignore[arg-type]
            raise RuntimeError("boom")
    assert "@value = NULL" in conn.executed[-1][0]
    assert engine.pooled.closed is True


def test_open_report_connection_invalidates_when_clear_fails() -> None:
    conn = FakeConnection()
    engine = FakeEngine(conn)
    with open_report_connection("T1", "U1", engine=engine):  # type: ignore[arg-type]
        conn.error = pyodbc.OperationalError("08S01", "link failure")
        conn.error_on = "@value = NULL"
    assert engine.pooled.invalidated is True
    assert engine.pooled.closed is False


def test_open_report_connection_set_failure_is_500_and_releases() -> None:
    conn = FakeConnection(error=pyodbc.Error("HY000", "nope"), error_on="@value = ?")
    engine = FakeEngine(conn)
    with pytest.raises(HTTPException) as exc_info:
        with open_report_connection("T1", "U1", engine=engine):  # type: ignore[arg-type]
            pytest.fail("body must not run")
    _assert_execution_failed(exc_info)
    assert engine.pooled.closed is True
