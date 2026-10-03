"""Report execution — validate criteria, run the report proc, encode rows for JSON."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from mtf.rpt.execution import EXECUTION_FAILED_MESSAGE, clamp_max_rows, execute_proc
from mtf.rpt.schemas import ReportRunRead
from mtf.rpt.services.criteria_validation import criteria_to_json, validate_report_criteria
from mtf.rpt.services.report_catalog import ReportCatalogService
from mtf.shared.exceptions import internal_error


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return datetime.fromisoformat(str(value))


def encode_report_value(data_type: str, value: Any) -> Any:
    """One proc value → its JSON form, driven by ``report_column.data_type``.

    ``int``/``decimal`` → number, ``date`` → ``YYYY-MM-DD``, ``datetime`` → ISO 8601
    (UTC, no offset), ``bool`` → ``true``/``false``, ``NULL`` → ``null``. Decimals become
    floats: browsers parse every JSON number as a double anyway.
    """
    if value is None:
        return None
    if data_type == "int":
        return int(value)
    if data_type == "decimal":
        return float(value)
    if data_type == "bool":
        return bool(value)
    if data_type == "date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return date.fromisoformat(str(value)).isoformat()
    if data_type == "datetime":
        return _to_datetime(value).isoformat()
    if isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


class ReportRunService:
    def __init__(self, db: Session) -> None:
        self._catalog = ReportCatalogService(db)

    def run(
        self,
        conn: Any,
        tenant_id: str,
        report_key: str,
        *,
        criteria: dict[str, Any] | None = None,
        max_rows: int | None = None,
    ) -> ReportRunRead:
        """Run ``report_key`` on ``conn`` (the request's session-context connection).

        Criteria are validated before the proc is touched; the proc's output must match
        the report's active columns exactly.
        """
        resolved = self._catalog.resolve(tenant_id, report_key)
        report = resolved.definition
        normalized = validate_report_criteria(criteria, resolved.criteria)
        effective_max_rows = clamp_max_rows(max_rows, cap=report.default_max_rows)

        result = execute_proc(
            conn,
            report.proc_name,
            [("@CriteriaJson", criteria_to_json(normalized))],
            max_rows=effective_max_rows,
            expected_columns=[c.column_name for c in resolved.columns],
        )

        position = {name: index for index, name in enumerate(result.columns)}
        layout = [(c.column_name, c.data_type, position[c.column_name]) for c in resolved.columns]
        rows: list[dict[str, Any]] = []
        for row in result.rows:
            encoded: dict[str, Any] = {}
            for name, data_type, index in layout:
                try:
                    encoded[name] = encode_report_value(data_type, row[index])
                except (TypeError, ValueError) as exc:
                    internal_error(
                        "REPORT_EXECUTION",
                        EXECUTION_FAILED_MESSAGE,
                        log_message=(
                            f"{report.proc_name} column {name!r} returned {row[index]!r}, "
                            f"not a {data_type}"
                        ),
                        cause=exc,
                    )
            rows.append(encoded)
        return ReportRunRead(
            report_key=report.report_key,
            row_count=len(rows),
            truncated=result.truncated,
            rows=rows,
        )
