"""One pooled pyodbc connection per request, with tenant/user ``SESSION_CONTEXT`` set on it."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine

from mtf.shared import database
from mtf.shared.exceptions import internal_error

logger = logging.getLogger(__name__)

EXECUTION_FAILED_MESSAGE = "The report could not be executed."

_SET_CONTEXT_SQL = (
    "EXEC sp_set_session_context @key = N'tenant_id', @value = ?; "
    "EXEC sp_set_session_context @key = N'user_id', @value = ?;"
)
_CLEAR_CONTEXT_SQL = (
    "EXEC sp_set_session_context @key = N'tenant_id', @value = NULL; "
    "EXEC sp_set_session_context @key = N'user_id', @value = NULL;"
)


def _run(dbapi_conn: Any, sql: str, *params: Any) -> None:
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute(sql, *params)
    finally:
        cursor.close()


@contextmanager
def open_report_connection(
    tenant_id: str,
    user_id: str,
    *,
    engine: Engine | None = None,
) -> Iterator[Any]:
    """Yield a raw pyodbc connection whose ``SESSION_CONTEXT`` carries this tenant and user.

    Every proc call for the request must run on the yielded connection: context set on one
    pooled connection is invisible on another. Keys are never set ``@read_only`` so they can
    be cleared before the connection goes back to the pool; if clearing fails, the
    connection is invalidated instead of returned.
    """
    pooled = (engine or database.engine).raw_connection()
    dbapi_conn = pooled.driver_connection
    try:
        try:
            _run(dbapi_conn, _SET_CONTEXT_SQL, tenant_id, user_id)
        except Exception as exc:
            internal_error(
                "REPORT_EXECUTION",
                EXECUTION_FAILED_MESSAGE,
                log_message="Could not set report session context",
                cause=exc,
            )
        yield dbapi_conn
    finally:
        try:
            _run(dbapi_conn, _CLEAR_CONTEXT_SQL)
        except Exception:
            logger.exception("Could not clear report session context; discarding connection")
            pooled.invalidate()
        else:
            pooled.close()
