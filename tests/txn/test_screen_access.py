"""Screen access: RBAC when the tenant has grants, else screen_permission."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from mtf.txn.services.screen_access import (
    ScreenAccessService,
    screen_permission_code,
    tenant_uses_screen_rbac,
)
from mtf.txn.services.screen_metadata import ScreenMetadataService
from mtf.txn.services.screen_permission import ScreenEffectivePermissions
from tests.txn.conftest import (
    SAMPLE_SCREEN_KEY,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_screen,
    tenant_user,
)

_ALLOWED = ScreenEffectivePermissions(
    can_view=True, can_add=True, can_edit=True, can_delete=False
)
_DENIED = ScreenEffectivePermissions(
    can_view=False, can_add=False, can_edit=False, can_delete=False
)


def test_screen_permission_code_maps_operations() -> None:
    assert screen_permission_code("lead", "view") == "screen.lead.view"
    assert screen_permission_code("lead", "add") == "screen.lead.create"
    assert screen_permission_code("lead", "edit") == "screen.lead.update"
    assert screen_permission_code("lead", "delete") == "screen.lead.delete"


def test_uses_rbac_requires_catalog_and_assignment() -> None:
    db = MagicMock()
    db.scalar.side_effect = [True, True]
    assert tenant_uses_screen_rbac(db, TEST_TENANT_ID, "lead") is True

    db.scalar.side_effect = [False]
    assert tenant_uses_screen_rbac(db, TEST_TENANT_ID, "lead") is False

    db.scalar.side_effect = [True, False]
    assert tenant_uses_screen_rbac(db, TEST_TENANT_ID, "lead") is False


def test_uses_rbac_is_memoized() -> None:
    db = MagicMock()
    db.scalar.side_effect = [True, True]
    svc = ScreenAccessService(db, resolver=MagicMock(), legacy=MagicMock())
    assert svc.uses_rbac(TEST_TENANT_ID, "lead") is True
    assert svc.uses_rbac(TEST_TENANT_ID, "lead") is True
    assert db.scalar.call_count == 2


def test_rbac_path_does_not_call_legacy() -> None:
    resolver = MagicMock()
    resolver.permission_codes.return_value = frozenset({"screen.lead.view"})
    legacy = MagicMock()
    svc = ScreenAccessService(MagicMock(), resolver=resolver, legacy=legacy)
    svc._uses_rbac[(TEST_TENANT_ID, "lead")] = True
    perms = svc.resolve(tenant_user(), "lead")
    assert perms.can_view is True
    assert perms.can_add is False
    assert perms.can_edit is False
    assert perms.can_delete is False
    legacy.resolve.assert_not_called()


def test_rbac_deny_does_not_fall_back_to_legacy() -> None:
    resolver = MagicMock()
    resolver.permission_codes.return_value = frozenset()
    legacy = MagicMock()
    legacy.resolve.return_value = _ALLOWED
    svc = ScreenAccessService(MagicMock(), resolver=resolver, legacy=legacy)
    svc._uses_rbac[(TEST_TENANT_ID, "lead")] = True
    with pytest.raises(HTTPException) as exc_info:
        svc.require(tenant_user(), "lead", "view")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "AUTH_FORBIDDEN"
    legacy.resolve.assert_not_called()


def test_legacy_path_when_tenant_has_no_rbac() -> None:
    resolver = MagicMock()
    legacy = MagicMock()
    legacy.resolve.return_value = _ALLOWED
    svc = ScreenAccessService(MagicMock(), resolver=resolver, legacy=legacy)
    svc._uses_rbac[(TEST_TENANT_ID, "lead")] = False
    perms = svc.require(tenant_user(), "lead", "view")
    assert perms.can_view is True
    resolver.permission_codes.assert_not_called()
    legacy.resolve.assert_called_once_with(TEST_TENANT_ID, TEST_USER_ID, "lead")


def test_legacy_deny_is_screen_forbidden() -> None:
    legacy = MagicMock()
    legacy.resolve.return_value = _DENIED
    svc = ScreenAccessService(MagicMock(), resolver=MagicMock(), legacy=legacy)
    svc._uses_rbac[(TEST_TENANT_ID, "lead")] = False
    with pytest.raises(HTTPException) as exc_info:
        svc.require(tenant_user(), "lead", "view")
    assert exc_info.value.detail["code"] == "SCREEN_FORBIDDEN"


def test_metadata_rbac_deny_is_auth_forbidden() -> None:
    access = MagicMock()
    access.resolve_with_screen.return_value = (minimal_screen(), _DENIED)
    access.uses_rbac.return_value = True
    service = ScreenMetadataService(MagicMock(), access=access)
    with pytest.raises(HTTPException) as exc_info:
        service.get_screen(
            TEST_TENANT_ID,
            TEST_USER_ID,
            SAMPLE_SCREEN_KEY,
            user=tenant_user(),
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "AUTH_FORBIDDEN"
