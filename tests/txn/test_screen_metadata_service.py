"""ScreenMetadataService — overrides, hide rules, lookups (mocked session)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from mtf.txn.services.screen_metadata import (
    ScreenMetadataService,
    effective_is_displayed,
)
from mtf.txn.services.screen_permission import ScreenEffectivePermissions
from tests.txn.conftest import (
    SAMPLE_FIELD_ID,
    SAMPLE_LOOKUP_ID,
    SAMPLE_SCREEN_KEY,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_config,
    minimal_field,
    minimal_lookup,
    minimal_lookup_column,
    minimal_screen,
    minimal_section,
)

_ALLOWED = ScreenEffectivePermissions(
    can_view=True, can_add=True, can_edit=True, can_delete=False
)
_ADD_ONLY = ScreenEffectivePermissions(
    can_view=False, can_add=True, can_edit=False, can_delete=False
)
_DENIED = ScreenEffectivePermissions(
    can_view=False, can_add=False, can_edit=False, can_delete=False
)


def _all(rows: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _service(
    *batches: list[object],
    perms: ScreenEffectivePermissions = _ALLOWED,
) -> ScreenMetadataService:
    perm_svc = MagicMock()
    perm_svc.resolve_with_screen.return_value = (minimal_screen(), perms)
    db = MagicMock()
    db.scalars.side_effect = [_all(list(batch)) for batch in batches]
    return ScreenMetadataService(db, permissions=perm_svc)


def test_required_field_without_default_cannot_be_hidden() -> None:
    field = minimal_field(is_required=True, default_value=None, is_displayed=True)
    override = minimal_config(is_displayed=False)
    assert effective_is_displayed(field, override) is True


def test_optional_field_can_be_hidden() -> None:
    field = minimal_field(is_required=False, is_displayed=True)
    override = minimal_config(is_displayed=False)
    assert effective_is_displayed(field, override) is False


def test_system_hidden_required_without_default_is_still_shown() -> None:
    field = minimal_field(is_required=True, default_value="  ", is_displayed=False)
    assert effective_is_displayed(field, None) is True


def test_get_screen_denies_when_no_operations_granted() -> None:
    service = _service(perms=_DENIED)
    with pytest.raises(HTTPException) as exc_info:
        service.get_screen(TEST_TENANT_ID, TEST_USER_ID, SAMPLE_SCREEN_KEY)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "SCREEN_FORBIDDEN"


def test_add_only_user_still_gets_metadata() -> None:
    field = minimal_field()
    service = _service([minimal_section()], [field], [], perms=_ADD_ONLY)
    result = service.get_screen(TEST_TENANT_ID, TEST_USER_ID, SAMPLE_SCREEN_KEY)
    assert result.permissions.can_add is True
    assert result.permissions.can_view is False
    assert result.sections[0].fields[0].field_key == "name"


def test_hidden_optional_field_and_empty_section_are_omitted() -> None:
    field = minimal_field(is_required=False)
    override = minimal_config(is_displayed=False)
    service = _service([minimal_section()], [field], [override])
    result = service.get_screen(TEST_TENANT_ID, TEST_USER_ID, SAMPLE_SCREEN_KEY)
    assert result.sections == []


def test_tenant_override_renames_and_reorders_field() -> None:
    field = minimal_field()
    override = minimal_config(display_name="Full Name", display_order=30)
    service = _service([minimal_section()], [field], [override])
    result = service.get_screen(TEST_TENANT_ID, TEST_USER_ID, SAMPLE_SCREEN_KEY)
    built = result.sections[0].fields[0]
    assert built.display_name == "Full Name"
    assert built.display_order == 30


def test_dropdown_includes_lookup_metadata_without_ids() -> None:
    field = minimal_field(
        field_key="owner_id",
        display_name="Owner",
        control_type="dropdown",
        lookup_id=SAMPLE_LOOKUP_ID,
        is_required=False,
    )
    lookup = minimal_lookup()
    column = minimal_lookup_column()
    service = _service(
        [minimal_section()],
        [field],
        [],
        [lookup],
        [column],
    )
    result = service.get_screen(TEST_TENANT_ID, TEST_USER_ID, SAMPLE_SCREEN_KEY)
    payload = result.model_dump()
    built = result.sections[0].fields[0]
    assert built.lookup is not None
    assert built.lookup.lookup_key == "sample_lookup"
    assert built.lookup.display_field_key == "name"
    assert built.lookup.columns[0].field_key == "name"
    blob = str(payload)
    assert SAMPLE_FIELD_ID not in blob
    assert SAMPLE_LOOKUP_ID not in blob
    assert "lookup_id" not in payload["sections"][0]["fields"][0]


def test_response_has_no_capabilities_block() -> None:
    service = _service([minimal_section()], [minimal_field()], [])
    payload = service.get_screen(
        TEST_TENANT_ID, TEST_USER_ID, SAMPLE_SCREEN_KEY
    ).model_dump()
    assert "capabilities" not in payload
    assert set(payload["permissions"]) == {"can_view", "can_add", "can_edit", "can_delete"}
