"""Detect database unique / duplicate-key violations from :exc:`sqlalchemy.exc.IntegrityError`."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError


def is_unique_constraint_violation(exc: IntegrityError) -> bool:
    """Return True when ``exc`` is a duplicate-key / unique-index violation (not a generic FK error).

    Works with SQL Server (pyodbc) and other drivers whose error text mentions duplicate keys or
    unique constraints.
    """
    parts: list[str] = [str(exc)]
    if exc.orig is not None:
        parts.append(str(exc.orig))
    msg = " ".join(parts).lower()
    if "foreign key" in msg or "reference constraint" in msg:
        return False
    return (
        "duplicate key" in msg
        or "unique constraint" in msg
        or "unique index" in msg
        or "violation of unique key" in msg
        or "cannot insert duplicate key" in msg
    )
