"""Unit tests for :mod:`app.shared.db_integrity`."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from mtf.shared.db_integrity import is_unique_constraint_violation


@pytest.mark.parametrize(
    ("orig_msg", "expected"),
    [
        ("Cannot insert duplicate key row in object 'tenant.tenant'.", True),
        ("Violation of UNIQUE KEY constraint 'UQ_tenant_subdomain'.", True),
        ("duplicate key value violates unique constraint", True),
        (
            "The INSERT statement conflicted with the FOREIGN KEY constraint "
            "\"FK_tenant_created_by\".",
            False,
        ),
        ("General database error", False),
    ],
)
def test_is_unique_constraint_violation(orig_msg: str, expected: bool) -> None:
    exc = IntegrityError("statement", {}, Exception(orig_msg))
    assert is_unique_constraint_violation(exc) is expected
