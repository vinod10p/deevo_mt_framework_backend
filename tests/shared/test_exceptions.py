"""Unit tests — validation_error / internal_error helpers."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from mtf.shared.exceptions import internal_error, validation_error


def test_validation_error_shape() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validation_error(
            "REPORT_CRITERIA", "Invalid report criteria", {"status": "Must be a string"}
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {
        "code": "REPORT_CRITERIA_INVALID",
        "message": "Invalid report criteria",
        "fields": {"status": "Must be a string"},
    }


def test_internal_error_is_generic_and_logs_details(caplog: pytest.LogCaptureFixture) -> None:
    cause = RuntimeError("SQL text with secrets")
    with pytest.raises(HTTPException) as exc_info:
        internal_error(
            "REPORT_EXECUTION",
            "The report could not be executed.",
            log_message="rpt.usp_x failed",
            cause=cause,
        )
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == {
        "code": "REPORT_EXECUTION_FAILED",
        "message": "The report could not be executed.",
    }
    assert exc_info.value.__cause__ is cause
    assert "rpt.usp_x failed" in caplog.text
    assert "SQL text with secrets" in caplog.text
