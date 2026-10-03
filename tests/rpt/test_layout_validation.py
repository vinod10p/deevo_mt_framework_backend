"""Unit tests — validate_report_layout."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from mtf.rpt.services import validate_report_layout
from tests.rpt.conftest import minimal_column


def _col(name: str, **flags: bool):
    base = {
        "is_displayable": True,
        "is_sortable": True,
        "is_groupable": False,
        "is_aggregatable": False,
    }
    base.update(flags)
    if not base["is_displayable"]:
        base.update(is_default_visible=False, is_sortable=False, is_groupable=False)
    return minimal_column(id=name, column_name=name, **base)


SPECS = [
    _col("name"),
    _col("account_type", is_groupable=True, is_aggregatable=True),
    _col("amount", is_aggregatable=True),
    _col("notes", is_sortable=False),
    _col("internal_id", is_displayable=False),
]

EMPTY = {"columns": [], "sort": [], "group": [], "aggregates": []}
_BAD_NAME = "column_name must be a non-empty string"


def _fields(layout: Any) -> dict[str, str]:
    with pytest.raises(HTTPException) as exc_info:
        validate_report_layout(layout, SPECS)
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert detail["code"] == "REPORT_LAYOUT_INVALID"
    return detail["fields"]


@pytest.mark.parametrize(
    "layout",
    [None, {}, {"columns": None, "sort": None, "group": None, "aggregates": None}],
)
def test_empty_layouts_normalize_to_all_sections(layout: Any) -> None:
    assert validate_report_layout(layout, SPECS) == EMPTY


def test_full_layout_normalized_with_defaults_and_order_kept() -> None:
    result = validate_report_layout(
        {
            "columns": [
                {"column_name": "amount", "visible": True, "width": 120},
                {"column_name": "name"},
                {"column_name": "internal_id", "visible": False},
            ],
            "sort": [{"column_name": "amount", "direction": "desc"}, {"column_name": "name"}],
            "group": ["account_type"],
            "aggregates": [{"column_name": "amount", "type": "sum"}],
        },
        SPECS,
    )
    assert result == {
        "columns": [
            {"column_name": "amount", "visible": True, "width": 120},
            {"column_name": "name", "visible": True, "width": None},
            {"column_name": "internal_id", "visible": False, "width": None},
        ],
        "sort": [
            {"column_name": "amount", "direction": "desc"},
            {"column_name": "name", "direction": "asc"},
        ],
        "group": ["account_type"],
        "aggregates": [{"column_name": "amount", "type": "sum"}],
    }


def test_layout_must_be_object() -> None:
    assert _fields(["columns"]) == {"layout": "Must be an object"}


@pytest.mark.parametrize("key", ["version", "filters", "colums"])
def test_unknown_top_level_keys_rejected(key: str) -> None:
    assert _fields({key: []}) == {key: "Unexpected key"}


@pytest.mark.parametrize("section", ["columns", "sort", "group", "aggregates"])
def test_sections_must_be_lists(section: str) -> None:
    assert _fields({section: {"column_name": "name"}}) == {section: "Must be a list"}


# --- column names --------------------------------------------------------------


@pytest.mark.parametrize(
    ("layout", "field", "message"),
    [
        ({"columns": [{"column_name": "nope"}]}, "columns[0]", "Unknown column 'nope'"),
        ({"columns": [{}]}, "columns[0]", _BAD_NAME),
        ({"columns": [{"column_name": ""}]}, "columns[0]", _BAD_NAME),
        ({"columns": [{"column_name": 5}]}, "columns[0]", _BAD_NAME),
        ({"group": ["nope"]}, "group[0]", "Unknown column 'nope'"),
        ({"group": [None]}, "group[0]", _BAD_NAME),
    ],
)
def test_column_name_must_exist(layout: dict, field: str, message: str) -> None:
    assert _fields(layout) == {field: message}


@pytest.mark.parametrize(
    ("layout", "field"),
    [
        ({"columns": [{"column_name": "name"}, {"column_name": "name"}]}, "columns[1]"),
        ({"sort": [{"column_name": "name"}, {"column_name": "name", "direction": "desc"}]},
         "sort[1]"),
        ({"group": ["account_type", "account_type"]}, "group[1]"),
        ({"aggregates": [{"column_name": "amount", "type": "sum"},
                         {"column_name": "amount", "type": "avg"}]}, "aggregates[1]"),
    ],
)
def test_duplicates_within_one_section_rejected(layout: dict, field: str) -> None:
    fields = _fields(layout)
    assert list(fields) == [field]
    assert fields[field].startswith("Duplicate column")


def test_same_column_allowed_across_sections() -> None:
    result = validate_report_layout(
        {
            "columns": [{"column_name": "account_type"}],
            "sort": [{"column_name": "account_type"}],
            "group": ["account_type"],
            "aggregates": [{"column_name": "account_type", "type": "count"}],
        },
        SPECS,
    )
    assert result["group"] == ["account_type"]


# --- capability flags ---------------------------------------------------------


@pytest.mark.parametrize(
    ("layout", "field", "message"),
    [
        ({"columns": [{"column_name": "internal_id"}]}, "columns[0]",
         "Column 'internal_id' cannot be displayed"),
        ({"sort": [{"column_name": "notes"}]}, "sort[0]", "Column 'notes' is not sortable"),
        ({"group": ["name"]}, "group[0]", "Column 'name' is not groupable"),
        ({"aggregates": [{"column_name": "name", "type": "count"}]}, "aggregates[0]",
         "Column 'name' is not aggregatable"),
    ],
)
def test_capability_flags_enforced(layout: dict, field: str, message: str) -> None:
    assert _fields(layout) == {field: message}


def test_hidden_non_displayable_column_allowed() -> None:
    result = validate_report_layout(
        {"columns": [{"column_name": "internal_id", "visible": False}]}, SPECS
    )
    assert result["columns"] == [{"column_name": "internal_id", "visible": False, "width": None}]


# --- item shape ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("layout", "field", "fragment"),
    [
        ({"columns": ["name"]}, "columns[0]", "Must be an object"),
        ({"columns": [{"column_name": "name", "hidden": True}]}, "columns[0]",
         "Unexpected keys: hidden"),
        ({"columns": [{"column_name": "name", "visible": "yes"}]}, "columns[0]", "visible"),
        ({"columns": [{"column_name": "name", "width": 0}]}, "columns[0]", "width"),
        ({"columns": [{"column_name": "name", "width": -5}]}, "columns[0]", "width"),
        ({"columns": [{"column_name": "name", "width": 12.5}]}, "columns[0]", "width"),
        ({"columns": [{"column_name": "name", "width": True}]}, "columns[0]", "width"),
        ({"columns": [{"column_name": "name", "width": "100"}]}, "columns[0]", "width"),
        ({"sort": [{"column_name": "name", "direction": "up"}]}, "sort[0]", "direction"),
        ({"sort": [{"column_name": "name", "direction": "ASC"}]}, "sort[0]", "direction"),
        ({"sort": ["name"]}, "sort[0]", "Must be an object"),
        ({"aggregates": [{"column_name": "amount"}]}, "aggregates[0]", "type must be one of"),
        ({"aggregates": [{"column_name": "amount", "type": "median"}]}, "aggregates[0]",
         "type must be one of"),
        ({"group": [{"column_name": "account_type"}]}, "group[0]", "non-empty string"),
    ],
)
def test_item_shape_errors(layout: dict, field: str, fragment: str) -> None:
    fields = _fields(layout)
    assert list(fields) == [field]
    assert fragment in fields[field]


def test_all_errors_reported_together() -> None:
    fields = _fields(
        {
            "columns": [{"column_name": "name"}, {"column_name": "nope"}],
            "sort": [{"column_name": "notes"}],
            "group": ["name"],
            "extra": 1,
        }
    )
    assert set(fields) == {"columns[1]", "sort[0]", "group[0]", "extra"}
