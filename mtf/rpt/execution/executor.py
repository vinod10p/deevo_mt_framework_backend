"""Parameterized stored-proc execution for report and lookup procs.

Shared by ``/run`` and ``/lookups``: proc-name check, bound parameters, statement timeout,
``TOP (@MaxRows + 1)`` truncation detection, and the exact output-column contract.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any, Never

import pyodbc

from mtf.rpt.execution.connection import EXECUTION_FAILED_MESSAGE
from mtf.shared.config import get_settings
from mtf.shared.exceptions import internal_error

_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_PROC_NAME_RE = re.compile(rf"({_IDENTIFIER})\.({_IDENTIFIER})")
_PARAM_NAME_RE = re.compile(rf"@{_IDENTIFIER}")
_TIMEOUT_SQLSTATES = frozenset({"HYT00", "HYT01"})

LOOKUP_COLUMNS = ("value", "label")
LOOKUP_DEFAULT_ROWS = 50
LOOKUP_MAX_ROWS = 200


@dataclass(frozen=True)
class ProcResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool


def _fail(log_message: str, cause: BaseException | None = None) -> Never:
    internal_error(
        "REPORT_EXECUTION",
        EXECUTION_FAILED_MESSAGE,
        log_message=log_message,
        cause=cause,
    )


def quote_proc_name(proc_name: str) -> str:
    """``schema.name`` (letters, digits, underscore) → ``[schema].[name]``.

    Proc names come from catalog metadata, never from the request; anything else is a
    metadata defect and surfaces as ``REPORT_EXECUTION_FAILED``.
    """
    match = _PROC_NAME_RE.fullmatch(proc_name or "")
    if match is None:
        _fail(f"Invalid proc name in report metadata: {proc_name!r}")
    schema, name = match.groups()
    return f"[{schema}].[{name}]"


def clamp_max_rows(requested: int | None, *, cap: int, default: int | None = None) -> int:
    """``max(1, min(requested, cap))``; ``default`` (else ``cap``) when the client omits it."""
    if requested is None:
        requested = cap if default is None else default
    return max(1, min(requested, cap))


def _check_columns(proc_name: str, columns: list[str], expected: Collection[str]) -> None:
    expected_set = set(expected)
    if len(set(columns)) == len(columns) and set(columns) == expected_set:
        return
    missing = sorted(expected_set - set(columns))
    unexpected = sorted(set(columns) - expected_set)
    _fail(
        f"Output contract mismatch for {proc_name}: columns={columns}, "
        f"missing={missing}, unexpected={unexpected}"
    )


def execute_proc(
    conn: Any,
    proc_name: str,
    params: Sequence[tuple[str, Any]],
    *,
    max_rows: int,
    expected_columns: Collection[str],
    timeout_seconds: int | None = None,
) -> ProcResult:
    """Run ``proc_name`` on ``conn`` with bound ``params`` plus ``@MaxRows = max_rows``.

    ``conn`` must be the connection from :func:`open_report_connection` for this request.
    Fetches at most ``max_rows + 1`` rows; the extra row only sets ``truncated``.
    """
    quoted = quote_proc_name(proc_name)
    bound = [*params, ("@MaxRows", max_rows)]
    for name, _ in bound:
        if _PARAM_NAME_RE.fullmatch(name) is None:
            _fail(f"Invalid parameter name for {proc_name}: {name!r}")
    sql = f"SET NOCOUNT ON; EXEC {quoted} " + ", ".join(f"{name} = ?" for name, _ in bound)
    values = [value for _, value in bound]

    if timeout_seconds is None:
        timeout_seconds = get_settings().report_query_timeout_seconds

    previous_timeout = conn.timeout
    conn.timeout = timeout_seconds
    cursor = conn.cursor()
    try:
        cursor.execute(sql, *values)
        while cursor.description is None:
            if not cursor.nextset():
                _fail(f"{proc_name} returned no result set")
        columns = [col[0] for col in cursor.description]
        _check_columns(proc_name, columns, expected_columns)
        rows = [tuple(row) for row in cursor.fetchmany(max_rows + 1)]
    except pyodbc.Error as exc:
        sqlstate = exc.args[0] if exc.args else None
        if sqlstate in _TIMEOUT_SQLSTATES:
            _fail(f"{proc_name} timed out after {timeout_seconds}s", exc)
        _fail(f"{proc_name} failed: {sql}", exc)
    finally:
        cursor.close()
        conn.timeout = previous_timeout

    truncated = len(rows) > max_rows
    return ProcResult(columns=columns, rows=rows[:max_rows], truncated=truncated)
