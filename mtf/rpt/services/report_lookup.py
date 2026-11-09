"""Report lookups — dropdown/multiselect options from a criterion's ``lookup_proc``."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from mtf.rpt.execution import (
    LOOKUP_COLUMNS,
    LOOKUP_DEFAULT_ROWS,
    LOOKUP_MAX_ROWS,
    clamp_max_rows,
    execute_proc,
)
from mtf.rpt.schemas import ReportLookupOption, ReportLookupRead
from mtf.rpt.services.report_catalog import ReportCatalogService


class ReportLookupService:
    def __init__(self, db: Session, *, catalog: ReportCatalogService | None = None) -> None:
        self._catalog = catalog or ReportCatalogService(db)

    def get_options(
        self,
        conn: Any,
        tenant_id: str,
        report_key: str,
        criteria_key: str,
        *,
        q: str | None = None,
        values: list[str] | None = None,
        limit: int | None = None,
    ) -> ReportLookupRead:
        """Run the lookup proc on ``conn`` (the request's session-context connection).

        ``q`` searches labels; ``values`` resolves labels for already-selected values.
        When ``values`` is given and ``limit`` is omitted, the default grows to fit them
        (still capped at ``LOOKUP_MAX_ROWS``).
        """
        criteria = self._catalog.get_lookup_criteria(tenant_id, report_key, criteria_key)

        search = q.strip() if q else ""
        selected = [v for v in (values or []) if v != ""]
        max_rows = clamp_max_rows(
            limit,
            cap=LOOKUP_MAX_ROWS,
            default=max(LOOKUP_DEFAULT_ROWS, len(selected)),
        )
        result = execute_proc(
            conn,
            criteria.lookup_proc,
            [
                ("@SearchText", search or None),
                ("@Values", json.dumps(selected, ensure_ascii=False) if selected else None),
            ],
            max_rows=max_rows,
            expected_columns=LOOKUP_COLUMNS,
        )

        value_at = result.columns.index("value")
        label_at = result.columns.index("label")
        items = [
            ReportLookupOption(
                value=str(row[value_at]),
                label=str(row[label_at]) if row[label_at] is not None else str(row[value_at]),
            )
            for row in result.rows
            if row[value_at] is not None
        ]
        return ReportLookupRead(items=items, has_more=result.truncated)
