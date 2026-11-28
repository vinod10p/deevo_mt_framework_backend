"""The application clock."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Current UTC time without tzinfo — the form stored in ``datetime2`` columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
