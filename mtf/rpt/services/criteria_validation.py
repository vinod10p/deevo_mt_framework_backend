"""Report criteria validation — shared by ``/run``, ``POST /views``, and ``PATCH /views``.

Shape comes from ``control_type`` (scalar, multiselect list, daterange ``{"from","to"}``);
scalar type comes from ``data_type``. Omitted criteria (``null``, ``""``, ``[]``, an
all-empty range) are dropped from the result so the proc sees "no filter".
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from mtf.shared.exceptions import validation_error

_SCALAR_CONTROLS = frozenset({"text", "number", "date", "dropdown", "bool"})
_RANGE_KEYS = frozenset({"from", "to"})
_INT_RE = re.compile(r"[+-]?\d+")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_INT_MIN, _INT_MAX = -(2**31), 2**31 - 1


class CriteriaSpec(Protocol):
    """The ``report_criteria`` fields validation needs (satisfied by the ORM model)."""

    criteria_key: str
    data_type: str
    control_type: str
    is_required: bool


class _CriteriaError(ValueError):
    pass


class _Omitted:
    pass


_OMITTED = _Omitted()


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value == "")


def _parse_int(value: Any) -> int:
    if isinstance(value, bool):
        raise _CriteriaError("Must be a whole number")
    if isinstance(value, float):
        if not value.is_integer():
            raise _CriteriaError("Must be a whole number")
        value = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if _INT_RE.fullmatch(text) is None:
            raise _CriteriaError("Must be a whole number")
        value = int(text)
    elif not isinstance(value, int):
        raise _CriteriaError("Must be a whole number")
    if not _INT_MIN <= value <= _INT_MAX:
        raise _CriteriaError("Number is out of range")
    return value


def _parse_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise _CriteriaError("Must be a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _CriteriaError("Must be a number")
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            parsed = Decimal(value.strip())
        except InvalidOperation:
            raise _CriteriaError("Must be a number") from None
        if not parsed.is_finite():
            raise _CriteriaError("Must be a number")
        return parsed
    raise _CriteriaError("Must be a number")


def _parse_date(value: Any) -> date:
    if isinstance(value, str) and _DATE_RE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise _CriteriaError("Must be a date (YYYY-MM-DD)")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(UTC).replace(tzinfo=None)
            return parsed
    raise _CriteriaError("Must be an ISO 8601 date-time")


def _parse_scalar(data_type: str, value: Any) -> Any:
    """Parse to a comparable Python value (``date``/``datetime`` kept as objects)."""
    if data_type == "string":
        if not isinstance(value, str):
            raise _CriteriaError("Must be a string")
        return value
    if data_type == "int":
        return _parse_int(value)
    if data_type == "decimal":
        return _parse_decimal(value)
    if data_type == "date":
        return _parse_date(value)
    if data_type == "datetime":
        return _parse_datetime(value)
    if data_type == "bool":
        if not isinstance(value, bool):
            raise _CriteriaError("Must be true or false")
        return value
    raise _CriteriaError(f"Unsupported data type {data_type!r}")


def _canonical(value: Any) -> Any:
    """``date`` → ``YYYY-MM-DD``, ``datetime`` → ISO 8601; other parsed values unchanged."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _normalize_list(data_type: str, raw: Any) -> Any:
    if raw is None:
        return _OMITTED
    if not isinstance(raw, list):
        raise _CriteriaError("Must be a list")
    if not raw:
        return _OMITTED
    result: list[Any] = []
    seen: set[Any] = set()
    for index, item in enumerate(raw):
        if _is_empty(item):
            raise _CriteriaError(f"Item {index}: must not be empty")
        if isinstance(item, (list, dict)):
            raise _CriteriaError(f"Item {index}: must be a single value")
        try:
            parsed = _canonical(_parse_scalar(data_type, item))
        except _CriteriaError as exc:
            raise _CriteriaError(f"Item {index}: {exc}") from None
        if parsed not in seen:
            seen.add(parsed)
            result.append(parsed)
    return result


def _normalize_range(data_type: str, raw: Any) -> Any:
    if raw is None:
        return _OMITTED
    if not isinstance(raw, Mapping):
        raise _CriteriaError("Must be an object with 'from' and/or 'to'")
    extra = sorted(set(raw) - _RANGE_KEYS)
    if extra:
        raise _CriteriaError(f"Unexpected keys: {', '.join(map(str, extra))}")

    bounds: dict[str, Any] = {}
    for key in ("from", "to"):
        value = raw.get(key)
        if _is_empty(value):
            continue
        try:
            bounds[key] = _parse_scalar(data_type, value)
        except _CriteriaError as exc:
            raise _CriteriaError(f"'{key}': {exc}") from None
    if not bounds:
        return _OMITTED
    if "from" in bounds and "to" in bounds and bounds["from"] > bounds["to"]:
        raise _CriteriaError("'from' must be on or before 'to'")
    return {key: _canonical(value) for key, value in bounds.items()}


def _normalize(spec: CriteriaSpec, raw: Any) -> Any:
    if spec.control_type == "multiselect":
        return _normalize_list(spec.data_type, raw)
    if spec.control_type == "daterange":
        return _normalize_range(spec.data_type, raw)
    if spec.control_type in _SCALAR_CONTROLS:
        if _is_empty(raw):
            return _OMITTED
        if isinstance(raw, (list, dict)):
            raise _CriteriaError("Must be a single value")
        return _canonical(_parse_scalar(spec.data_type, raw))
    raise _CriteriaError(f"Unsupported control type {spec.control_type!r}")


def validate_report_criteria(
    criteria: Mapping[str, Any] | None,
    specs: Iterable[CriteriaSpec],
) -> dict[str, Any]:
    """Validate and normalize client criteria against a report's active criteria rows.

    Returns only supplied criteria, in ``specs`` order, as canonical values: ``str``,
    ``int``, ``Decimal``, ``bool``, ``YYYY-MM-DD`` / ISO 8601 strings, lists of those,
    or ``{"from", "to"}`` dicts. Raises ``422 REPORT_CRITERIA_INVALID`` with a ``fields``
    map keyed by ``criteria_key`` on any failure.
    """
    if criteria is None:
        criteria = {}
    if not isinstance(criteria, Mapping):
        validation_error(
            "REPORT_CRITERIA", "Invalid report criteria", {"criteria": "Must be an object"}
        )

    specs_by_key = {spec.criteria_key: spec for spec in specs}
    errors: dict[str, str] = {
        str(key): "Unknown criterion" for key in criteria if key not in specs_by_key
    }
    normalized: dict[str, Any] = {}
    for key, spec in specs_by_key.items():
        try:
            value = _normalize(spec, criteria.get(key))
        except _CriteriaError as exc:
            errors[key] = str(exc)
            continue
        if value is _OMITTED:
            if spec.is_required:
                errors[key] = "This field is required"
            continue
        normalized[key] = value

    if errors:
        validation_error("REPORT_CRITERIA", "Invalid report criteria", errors)
    return normalized


def _encode(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, list):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, Mapping):
        members = (
            f"{json.dumps(str(key), ensure_ascii=False)}:{_encode(item)}"
            for key, item in value.items()
        )
        return "{" + ",".join(members) + "}"
    return json.dumps(value, ensure_ascii=False)


def criteria_to_json(normalized: Mapping[str, Any]) -> str:
    """Serialize :func:`validate_report_criteria` output for ``@CriteriaJson``.

    ``Decimal`` values are written as exact JSON numbers (``json.dumps`` can't do that).
    """
    return _encode(normalized)
