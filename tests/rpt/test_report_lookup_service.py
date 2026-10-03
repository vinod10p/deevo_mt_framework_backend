"""ReportLookupService — parameter building and option mapping (execute_proc patched)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from mtf.rpt.execution import ProcResult
from mtf.rpt.services import ReportLookupService
from mtf.rpt.services import report_lookup as lookup_module
from tests.rpt.conftest import TEST_TENANT_ID, minimal_criteria

CONN = object()


class Recorder(list):
    """``execute_proc`` calls, plus the ``ProcResult`` the fake returns."""

    result = ProcResult(columns=["value", "label"], rows=[], truncated=False)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorded = Recorder()

    def fake_execute_proc(conn: Any, proc_name: str, params: Any, **kwargs: Any) -> ProcResult:
        recorded.append({"conn": conn, "proc_name": proc_name, "params": dict(params), **kwargs})
        return recorded.result

    monkeypatch.setattr(lookup_module, "execute_proc", fake_execute_proc)
    return recorded


def _service(criterion: Any = None) -> tuple[ReportLookupService, MagicMock]:
    service = ReportLookupService(MagicMock())
    catalog = MagicMock()
    catalog.get_lookup_criteria.return_value = criterion or minimal_criteria()
    service._catalog = catalog
    return service, catalog


def test_defaults_bind_nulls_and_default_limit(calls: list[dict[str, Any]]) -> None:
    service, catalog = _service()

    service.get_options(CONN, TEST_TENANT_ID, "tenant_account_list", "account_type")

    catalog.get_lookup_criteria.assert_called_once_with(
        TEST_TENANT_ID, "tenant_account_list", "account_type"
    )
    call = calls[0]
    assert call["conn"] is CONN
    assert call["proc_name"] == "rpt.usp_lookup_account_type"
    assert call["params"] == {"@SearchText": None, "@Values": None}
    assert call["max_rows"] == 50
    assert list(call["expected_columns"]) == ["value", "label"]


@pytest.mark.parametrize(("q", "bound"), [("  cust ", "cust"), ("", None), ("   ", None)])
def test_search_text_trimmed_and_blank_is_null(
    calls: list[dict[str, Any]], q: str, bound: str | None
) -> None:
    service, _ = _service()
    service.get_options(CONN, TEST_TENANT_ID, "r", "c", q=q)
    assert calls[0]["params"]["@SearchText"] == bound


def test_values_bound_as_json_array(calls: list[dict[str, Any]]) -> None:
    service, _ = _service()
    service.get_options(CONN, TEST_TENANT_ID, "r", "c", values=["C001", "", 'O"Brien', "é"])
    assert calls[0]["params"]["@Values"] == '["C001", "O\\"Brien", "é"]'


def test_empty_values_list_is_null(calls: list[dict[str, Any]]) -> None:
    service, _ = _service()
    service.get_options(CONN, TEST_TENANT_ID, "r", "c", values=["", ""])
    assert calls[0]["params"]["@Values"] is None


@pytest.mark.parametrize(
    ("limit", "values", "expected"),
    [
        (10, None, 10),
        (0, None, 1),
        (5000, None, 200),
        (None, [str(i) for i in range(80)], 80),
        (None, [str(i) for i in range(500)], 200),
        (5, [str(i) for i in range(80)], 5),
    ],
)
def test_limit_clamped(
    calls: list[dict[str, Any]], limit: int | None, values: list[str] | None, expected: int
) -> None:
    service, _ = _service()
    service.get_options(CONN, TEST_TENANT_ID, "r", "c", values=values, limit=limit)
    assert calls[0]["max_rows"] == expected


def test_rows_mapped_to_string_options(calls: Recorder) -> None:
    calls.result = ProcResult(
        columns=["label", "value"],
        rows=[("Customer", "customer"), ("Seven", 7), (None, "no_label"), ("Skipped", None)],
        truncated=True,
    )
    service, _ = _service()

    result = service.get_options(CONN, TEST_TENANT_ID, "r", "c")

    assert [(o.value, o.label) for o in result.items] == [
        ("customer", "Customer"),
        ("7", "Seven"),
        ("no_label", "no_label"),
    ]
    assert result.has_more is True
