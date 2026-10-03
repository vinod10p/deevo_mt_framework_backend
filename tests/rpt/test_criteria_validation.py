"""Unit tests — validate_report_criteria / criteria_to_json."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from mtf.rpt.services import criteria_to_json, validate_report_criteria
from tests.rpt.conftest import minimal_criteria


def _spec(key: str, data_type: str, control_type: str, *, required: bool = False):
    return minimal_criteria(
        criteria_key=key,
        data_type=data_type,
        control_type=control_type,
        is_required=required,
        lookup_proc=None,
    )


SPECS = [
    _spec("account_type", "string", "multiselect"),
    _spec("status", "string", "dropdown"),
    _spec("created_date", "date", "daterange"),
    _spec("min_qty", "int", "number"),
    _spec("min_amount", "decimal", "number"),
    _spec("is_active", "bool", "bool"),
    _spec("as_of", "datetime", "date"),
    _spec("ids", "int", "multiselect"),
]


def _fields(criteria: Any, specs=SPECS) -> dict[str, str]:
    with pytest.raises(HTTPException) as exc_info:
        validate_report_criteria(criteria, specs)
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert detail["code"] == "REPORT_CRITERIA_INVALID"
    return detail["fields"]


def test_none_and_empty_criteria_normalize_to_empty() -> None:
    assert validate_report_criteria(None, SPECS) == {}
    assert validate_report_criteria({}, SPECS) == {}


def test_full_valid_criteria_normalized_in_spec_order() -> None:
    result = validate_report_criteria(
        {
            "is_active": True,
            "status": "active",
            "account_type": ["customer", "vendor"],
            "created_date": {"from": "2026-01-01", "to": "2026-12-31"},
            "min_qty": "42",
            "min_amount": "10.50",
            "as_of": "2026-03-01T10:00:00Z",
            "ids": ["1", 2],
        },
        SPECS,
    )
    assert list(result) == [
        "account_type", "status", "created_date", "min_qty",
        "min_amount", "is_active", "as_of", "ids",
    ]
    assert result["account_type"] == ["customer", "vendor"]
    assert result["created_date"] == {"from": "2026-01-01", "to": "2026-12-31"}
    assert result["min_qty"] == 42
    assert result["min_amount"] == Decimal("10.50")
    assert result["is_active"] is True
    assert result["as_of"] == "2026-03-01T10:00:00"
    assert result["ids"] == [1, 2]


@pytest.mark.parametrize(
    "criteria",
    [
        {"status": None},
        {"status": ""},
        {"account_type": []},
        {"account_type": None},
        {"created_date": {"from": None, "to": None}},
        {"created_date": {"from": "", "to": ""}},
        {"created_date": {}},
        {"created_date": None},
    ],
)
def test_empty_values_are_omitted(criteria: dict[str, Any]) -> None:
    assert validate_report_criteria(criteria, SPECS) == {}


@pytest.mark.parametrize(
    "criteria",
    [{}, {"status": None}, {"status": ""}],
)
def test_required_criterion_missing_or_empty(criteria: dict[str, Any]) -> None:
    specs = [_spec("status", "string", "dropdown", required=True)]
    assert _fields(criteria, specs) == {"status": "This field is required"}


def test_required_daterange_all_empty_fails() -> None:
    specs = [_spec("created_date", "date", "daterange", required=True)]
    fields = _fields({"created_date": {"from": None, "to": None}}, specs)
    assert fields == {"created_date": "This field is required"}


def test_unknown_key_rejected() -> None:
    assert _fields({"tenant_id": "x"}) == {"tenant_id": "Unknown criterion"}


def test_all_errors_reported_together() -> None:
    fields = _fields({"status": 5, "min_qty": "abc", "bogus": 1})
    assert set(fields) == {"status", "min_qty", "bogus"}


def test_criteria_must_be_object() -> None:
    assert _fields(["status"]) == {"criteria": "Must be an object"}


# --- shape by control_type ---------------------------------------------------


def test_scalar_control_rejects_list_and_object() -> None:
    assert _fields({"status": ["a"]})["status"] == "Must be a single value"
    assert _fields({"status": {"a": 1}})["status"] == "Must be a single value"


def test_multiselect_requires_list() -> None:
    assert _fields({"account_type": "customer"})["account_type"] == "Must be a list"


def test_multiselect_rejects_empty_and_nested_items() -> None:
    assert "Item 1" in _fields({"account_type": ["a", None]})["account_type"]
    assert "Item 0" in _fields({"account_type": [["a"]]})["account_type"]


def test_multiselect_string_rejects_numbers() -> None:
    assert _fields({"account_type": [100, 200]})["account_type"] == "Item 0: Must be a string"


def test_multiselect_dedupes_preserving_order() -> None:
    result = validate_report_criteria({"account_type": ["b", "a", "b"]}, SPECS)
    assert result["account_type"] == ["b", "a"]


def test_daterange_requires_object_and_known_keys() -> None:
    assert "object" in _fields({"created_date": "2026-01-01"})["created_date"]
    assert "Unexpected keys: start" in _fields({"created_date": {"start": "2026-01-01"}})[
        "created_date"
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"from": "2026-01-01"}, {"from": "2026-01-01"}),
        ({"to": "2026-12-31"}, {"to": "2026-12-31"}),
        ({"from": "2026-01-01", "to": None}, {"from": "2026-01-01"}),
        ({"from": "2026-05-05", "to": "2026-05-05"}, {"from": "2026-05-05", "to": "2026-05-05"}),
    ],
)
def test_partial_and_single_day_ranges_valid(value: dict, expected: dict) -> None:
    assert validate_report_criteria({"created_date": value}, SPECS)["created_date"] == expected


def test_daterange_from_after_to_rejected() -> None:
    fields = _fields({"created_date": {"from": "2026-12-31", "to": "2026-01-01"}})
    assert fields["created_date"] == "'from' must be on or before 'to'"


def test_daterange_bad_bound_names_the_bound() -> None:
    fields = _fields({"created_date": {"from": "2026-13-01"}})
    assert fields["created_date"].startswith("'from':")


# --- scalar type by data_type ------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), [(42, 42), ("42", 42), (" -7 ", -7), (10.0, 10)])
def test_int_accepts_integers_and_integer_strings(raw: Any, expected: int) -> None:
    assert validate_report_criteria({"min_qty": raw}, SPECS)["min_qty"] == expected


@pytest.mark.parametrize("raw", [10.75, "10.75", "abc", True, "1e3", 2**31])
def test_int_rejects_non_integers(raw: Any) -> None:
    assert "min_qty" in _fields({"min_qty": raw})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(5, Decimal(5)), (10.75, Decimal("10.75")), ("0.1", Decimal("0.1")), ("-3", Decimal(-3))],
)
def test_decimal_accepts_numbers_and_numeric_strings(raw: Any, expected: Decimal) -> None:
    assert validate_report_criteria({"min_amount": raw}, SPECS)["min_amount"] == expected


@pytest.mark.parametrize("raw", ["abc", "NaN", "Infinity", False, float("inf")])
def test_decimal_rejects_non_numbers(raw: Any) -> None:
    assert _fields({"min_amount": raw})["min_amount"] == "Must be a number"


@pytest.mark.parametrize("raw", ["true", 1, 0, "false"])
def test_bool_accepts_only_json_booleans(raw: Any) -> None:
    assert _fields({"is_active": raw})["is_active"] == "Must be true or false"


def test_bool_false_is_a_value_not_omitted() -> None:
    assert validate_report_criteria({"is_active": False}, SPECS) == {"is_active": False}


@pytest.mark.parametrize("raw", ["01/02/2026", "20260102", "2026-02-30", 20260102])
def test_date_requires_yyyy_mm_dd(raw: Any) -> None:
    fields = _fields({"created_date": {"from": raw}})
    assert "Must be a date (YYYY-MM-DD)" in fields["created_date"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-01T10:00:00", "2026-03-01T10:00:00"),
        ("2026-03-01T10:00:00+02:00", "2026-03-01T08:00:00"),
        ("2026-03-01", "2026-03-01T00:00:00"),
    ],
)
def test_datetime_normalized_to_naive_utc(raw: str, expected: str) -> None:
    assert validate_report_criteria({"as_of": raw}, SPECS)["as_of"] == expected


def test_datetime_rejects_garbage() -> None:
    assert _fields({"as_of": "yesterday"})["as_of"] == "Must be an ISO 8601 date-time"


# --- criteria_to_json --------------------------------------------------------


def test_criteria_to_json_round_trips_and_keeps_decimals_exact() -> None:
    normalized = validate_report_criteria(
        {
            "account_type": ["customer", "véndor"],
            "min_amount": "12345678901234567.89",
            "is_active": False,
            "created_date": {"from": "2026-01-01"},
        },
        SPECS,
    )
    text = criteria_to_json(normalized)
    assert '"min_amount":12345678901234567.89' in text
    parsed = json.loads(text, parse_float=Decimal)
    assert parsed == {
        "account_type": ["customer", "véndor"],
        "created_date": {"from": "2026-01-01"},
        "min_amount": Decimal("12345678901234567.89"),
        "is_active": False,
    }


def test_criteria_to_json_empty() -> None:
    assert criteria_to_json({}) == "{}"
