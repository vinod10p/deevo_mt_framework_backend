"""Report execution infrastructure — session-context connection and proc executor."""

from mtf.rpt.execution.connection import EXECUTION_FAILED_MESSAGE, open_report_connection
from mtf.rpt.execution.executor import (
    LOOKUP_COLUMNS,
    LOOKUP_DEFAULT_ROWS,
    LOOKUP_MAX_ROWS,
    ProcResult,
    clamp_max_rows,
    execute_proc,
    quote_proc_name,
)

__all__ = [
    "EXECUTION_FAILED_MESSAGE",
    "LOOKUP_COLUMNS",
    "LOOKUP_DEFAULT_ROWS",
    "LOOKUP_MAX_ROWS",
    "ProcResult",
    "clamp_max_rows",
    "execute_proc",
    "open_report_connection",
    "quote_proc_name",
]
