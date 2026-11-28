"""Run ``sql/*.sql`` scripts from integration tests against the configured database.

The scripts are written for SSMS: ``GO`` separates batches and most start with
``USE [deevo_app_dev2];``. Tests must run them against the database in the settings
(dev3 now), never the one named in the script, so every ``USE`` statement is removed —
including one that sits after the header comment inside the first batch.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import text

from mtf.shared.database import engine

_GO_LINE = re.compile(r"^\s*GO\s*$", re.IGNORECASE)
_USE_LINE = re.compile(r"^\s*USE\s+\[?[\w$]+\]?\s*;?\s*$", re.IGNORECASE)


def split_batches(sql: str) -> list[str]:
    """Split a script on ``GO`` lines and drop ``USE`` lines; empty batches are skipped."""
    batches: list[str] = []
    current: list[str] = []
    for line in sql.splitlines():
        if _GO_LINE.match(line):
            batches.append("\n".join(current).strip())
            current = []
        elif not _USE_LINE.match(line):
            current.append(line)
    batches.append("\n".join(current).strip())
    return [batch for batch in batches if batch]


def apply_sql_script(path: str | Path) -> None:
    """Run every batch of ``path`` in autocommit mode on the configured database.

    Raises ``AssertionError`` if the connection ends up on another database, so a
    script can never silently send later tests' writes somewhere else.
    """
    sql = Path(path).read_text(encoding="utf-8")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        expected_db = conn.execute(text("SELECT DB_NAME()")).scalar_one()
        try:
            for batch in split_batches(sql):
                conn.execute(text(batch))
        finally:
            # Scripts set NOCOUNT / XACT_ABORT ON; a pooled connection that keeps NOCOUNT
            # makes SQLAlchemy see rowcount -1 (StaleDataError) in later tests.
            conn.execute(text("SET NOCOUNT OFF; SET XACT_ABORT OFF"))
            current_db = conn.execute(text("SELECT DB_NAME()")).scalar_one()
            if current_db != expected_db:
                conn.execute(text(f"USE [{expected_db}]"))
        assert current_db == expected_db, (
            f"{Path(path).name} switched the connection from {expected_db} to {current_db}"
        )
