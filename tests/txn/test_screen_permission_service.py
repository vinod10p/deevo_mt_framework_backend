"""Screen permission rules and ScreenPermissionService (mocked session)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import mssql

from mtf.txn.services.screen_permission import (
    ScreenPermissionService,
    resolve_screen_permissions,
)
from tests.txn.conftest import (
    SAMPLE_SCREEN_ID,
    SAMPLE_SCREEN_KEY,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_permission,
    minimal_screen,
)


def _flags(
    perms: object,
) -> tuple[bool, bool, bool, bool]:
    return (perms.can_view, perms.can_add, perms.can_edit, perms.can_delete)  # type: ignore[attr-defined]


def test_open_no_row_follows_screen_capabilities() -> None:
    screen = minimal_screen(allow_delete=False)
    assert _flags(resolve_screen_permissions(screen, None)) == (True, True, True, False)


def test_open_no_row_edit_and_delete_require_view() -> None:
    screen = minimal_screen(allow_view=False, allow_edit=True, allow_delete=True)
    assert _flags(resolve_screen_permissions(screen, None)) == (False, True, False, False)


def test_restricted_no_row_denies_all() -> None:
    screen = minimal_screen(permission_mode="restricted")
    assert _flags(resolve_screen_permissions(screen, None)) == (False, False, False, False)


def test_active_row_is_capped_by_screen_allow_flags() -> None:
    screen = minimal_screen(allow_delete=False)
    row = minimal_permission(can_delete=True)
    assert _flags(resolve_screen_permissions(screen, row)) == (True, True, True, False)


def test_active_row_add_only_does_not_require_view() -> None:
    screen = minimal_screen()
    row = minimal_permission(can_view=False, can_add=True, can_edit=False, can_delete=False)
    assert _flags(resolve_screen_permissions(screen, row)) == (False, True, False, False)


def test_active_row_edit_requires_view() -> None:
    screen = minimal_screen()
    row = minimal_permission(can_view=False, can_edit=True)
    perms = resolve_screen_permissions(screen, row)
    assert perms.can_edit is False


def test_can_access_false_denies_all() -> None:
    screen = minimal_screen()
    row = minimal_permission(can_access=False, can_view=True, can_add=True)
    assert _flags(resolve_screen_permissions(screen, row)) == (False, False, False, False)


def test_inactive_row_denies_and_does_not_fall_back_to_open() -> None:
    screen = minimal_screen(permission_mode="open")
    row = minimal_permission(is_active=False)
    assert _flags(resolve_screen_permissions(screen, row)) == (False, False, False, False)


def test_allows_matches_operation_flags() -> None:
    perms = resolve_screen_permissions(minimal_screen(allow_delete=False), None)
    assert perms.allows("view") is True
    assert perms.allows("add") is True
    assert perms.allows("edit") is True
    assert perms.allows("delete") is False
    assert perms.any_granted() is True


def _db_returning_first(*rows: object) -> MagicMock:
    db = MagicMock()
    results = []
    for row in rows:
        result = MagicMock()
        result.first.return_value = row
        results.append(result)
    db.scalars.side_effect = results
    return db


def _stmt_sql(stmt: object) -> str:
    return str(stmt.compile(dialect=mssql.dialect()))


def test_service_resolves_open_screen_with_no_permission_row() -> None:
    screen = minimal_screen()
    db = _db_returning_first(screen, None)

    perms = ScreenPermissionService(db).resolve(TEST_TENANT_ID, TEST_USER_ID, SAMPLE_SCREEN_KEY)

    assert perms.can_view is True
    screen_sql = _stmt_sql(db.scalars.call_args_list[0].args[0])
    assert "is_deleted" in screen_sql
    assert "is_active" in screen_sql
    perm_sql = _stmt_sql(db.scalars.call_args_list[1].args[0])
    assert "is_deleted" in perm_sql
    assert SAMPLE_SCREEN_ID in perm_sql or "screen_id" in perm_sql


def test_service_treats_missing_screen_as_404() -> None:
    db = _db_returning_first(None)

    with pytest.raises(HTTPException) as exc_info:
        ScreenPermissionService(db).resolve(TEST_TENANT_ID, TEST_USER_ID, "missing")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "SCREEN_NOT_FOUND"


def test_service_passes_inactive_permission_row_to_resolver() -> None:
    screen = minimal_screen(permission_mode="open")
    row = minimal_permission(is_active=False)
    db = _db_returning_first(screen, row)

    perms = ScreenPermissionService(db).resolve(TEST_TENANT_ID, TEST_USER_ID, SAMPLE_SCREEN_KEY)

    assert perms.any_granted() is False


def test_resolve_for_screen_uses_live_permission_row() -> None:
    db = MagicMock()
    result = MagicMock()
    result.first.return_value = minimal_permission(can_add=False)
    db.scalars.return_value = result

    perms = ScreenPermissionService(db).resolve_for_screen(
        TEST_TENANT_ID, TEST_USER_ID, minimal_screen()
    )

    assert perms.can_view is True
    assert perms.can_add is False


def test_deleted_permission_row_is_not_queried_as_live() -> None:
    """Service SQL omits deleted rows, so they resolve like 'no row'."""
    screen = minimal_screen(permission_mode="restricted")
    db = _db_returning_first(screen, None)

    perms = ScreenPermissionService(db).resolve(TEST_TENANT_ID, TEST_USER_ID, SAMPLE_SCREEN_KEY)

    assert perms.any_granted() is False
    perm_sql = _stmt_sql(db.scalars.call_args_list[1].args[0]).lower()
    assert "is_deleted" in perm_sql
