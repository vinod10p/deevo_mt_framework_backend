"""Saved-view layout validation — shared by ``POST /views`` and ``PATCH /views``.

Layout shape (the client never sends ``version``; array order is display/sort/group order)::

    {
      "columns":    [{"column_name": "name", "visible": true, "width": 240}],
      "sort":       [{"column_name": "name", "direction": "asc"}],
      "group":      ["account_type"],
      "aggregates": [{"column_name": "amount", "type": "sum"}]
    }

A layout can never do more than the grid UI allows: every column must exist in the
report's active ``report_column`` set and carry the matching capability flag.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from mtf.shared.exceptions import validation_error

LAYOUT_SECTIONS = ("columns", "sort", "group", "aggregates")
_SORT_DIRECTIONS = ("asc", "desc")
_AGGREGATE_TYPES = ("sum", "avg", "count", "min", "max")
_COLUMN_KEYS = frozenset({"column_name", "visible", "width"})
_SORT_KEYS = frozenset({"column_name", "direction"})
_AGGREGATE_KEYS = frozenset({"column_name", "type"})


class ColumnSpec(Protocol):
    """The ``report_column`` fields validation needs (satisfied by the ORM model)."""

    column_name: str
    is_displayable: bool
    is_sortable: bool
    is_groupable: bool
    is_aggregatable: bool


class _LayoutError(ValueError):
    pass


class _Section:
    """Validates one layout array; column names may appear at most once per array."""

    def __init__(self, columns: Mapping[str, ColumnSpec]) -> None:
        self._columns = columns
        self._seen: set[str] = set()

    def column(self, name: Any, *, flag: str, flag_message: str) -> str:
        if not isinstance(name, str) or not name:
            raise _LayoutError("column_name must be a non-empty string")
        spec = self._columns.get(name)
        if spec is None:
            raise _LayoutError(f"Unknown column {name!r}")
        if name in self._seen:
            raise _LayoutError(f"Duplicate column {name!r}")
        if flag and not getattr(spec, flag):
            raise _LayoutError(f"Column {name!r} {flag_message}")
        self._seen.add(name)
        return name


def _object(item: Any, allowed: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(item, Mapping):
        raise _LayoutError("Must be an object")
    extra = sorted(str(key) for key in set(item) - allowed)
    if extra:
        raise _LayoutError(f"Unexpected keys: {', '.join(extra)}")
    return item


def _column_item(item: Any, section: _Section) -> dict[str, Any]:
    obj = _object(item, _COLUMN_KEYS)
    visible = obj.get("visible", True)
    if not isinstance(visible, bool):
        raise _LayoutError("visible must be true or false")
    width = obj.get("width")
    if width is not None and (isinstance(width, bool) or not isinstance(width, int) or width <= 0):
        raise _LayoutError("width must be a positive integer or null")
    name = section.column(
        obj.get("column_name"),
        flag="is_displayable" if visible else "",
        flag_message="cannot be displayed",
    )
    return {"column_name": name, "visible": visible, "width": width}


def _sort_item(item: Any, section: _Section) -> dict[str, Any]:
    obj = _object(item, _SORT_KEYS)
    direction = obj.get("direction", "asc")
    if direction not in _SORT_DIRECTIONS:
        raise _LayoutError("direction must be 'asc' or 'desc'")
    name = section.column(
        obj.get("column_name"), flag="is_sortable", flag_message="is not sortable"
    )
    return {"column_name": name, "direction": direction}


def _group_item(item: Any, section: _Section) -> str:
    return section.column(item, flag="is_groupable", flag_message="is not groupable")


def _aggregate_item(item: Any, section: _Section) -> dict[str, Any]:
    obj = _object(item, _AGGREGATE_KEYS)
    agg_type = obj.get("type")
    if agg_type not in _AGGREGATE_TYPES:
        raise _LayoutError(f"type must be one of {', '.join(_AGGREGATE_TYPES)}")
    name = section.column(
        obj.get("column_name"), flag="is_aggregatable", flag_message="is not aggregatable"
    )
    return {"column_name": name, "type": agg_type}


_ITEM_VALIDATORS = {
    "columns": _column_item,
    "sort": _sort_item,
    "group": _group_item,
    "aggregates": _aggregate_item,
}


def validate_report_layout(
    layout: Mapping[str, Any] | None,
    specs: Iterable[ColumnSpec],
) -> dict[str, list[Any]]:
    """Validate and normalize a client layout against a report's active columns.

    Returns all four sections (missing or ``null`` → ``[]``) with defaults filled in:
    ``visible`` → ``true``, ``width`` → ``null``, ``direction`` → ``"asc"``. Raises
    ``422 REPORT_LAYOUT_INVALID`` with a ``fields`` map keyed like ``"sort[0]"``.
    """
    if layout is None:
        layout = {}
    if not isinstance(layout, Mapping):
        validation_error("REPORT_LAYOUT", "Invalid report layout", {"layout": "Must be an object"})

    columns = {spec.column_name: spec for spec in specs}
    errors: dict[str, str] = {
        str(key): "Unexpected key" for key in layout if key not in LAYOUT_SECTIONS
    }
    normalized: dict[str, list[Any]] = {}
    for key in LAYOUT_SECTIONS:
        raw = layout.get(key)
        normalized[key] = []
        if raw is None:
            continue
        if not isinstance(raw, list):
            errors[key] = "Must be a list"
            continue
        section = _Section(columns)
        validate_item = _ITEM_VALIDATORS[key]
        for index, item in enumerate(raw):
            try:
                normalized[key].append(validate_item(item, section))
            except _LayoutError as exc:
                errors[f"{key}[{index}]"] = str(exc)

    if errors:
        validation_error("REPORT_LAYOUT", "Invalid report layout", errors)
    return normalized
