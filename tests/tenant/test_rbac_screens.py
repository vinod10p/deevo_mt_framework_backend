"""enable_screen_rbac / tenant_has_screen_rbac — no database."""

from __future__ import annotations

from unittest.mock import MagicMock

from mtf.tenant.models.tenant_setting import TenantSetting
from mtf.tenant.services.rbac_screens import (
    RBAC_SCREENS_KEY,
    RBAC_SCREENS_ON,
    enable_screen_rbac,
    tenant_has_screen_rbac,
)
from tests.tenant.conftest import TEST_TENANT_ID, TEST_USER_ID


def _added(db: MagicMock, model: type) -> list[object]:
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], model)]


def test_enable_screen_rbac_inserts_on_when_missing() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = None
    assert enable_screen_rbac(db, tenant_id=TEST_TENANT_ID, created_by=TEST_USER_ID) is True
    [row] = _added(db, TenantSetting)
    assert row.tenant_id == TEST_TENANT_ID
    assert row.key == RBAC_SCREENS_KEY
    assert row.value == RBAC_SCREENS_ON
    assert row.created_by == TEST_USER_ID


def test_enable_screen_rbac_is_idempotent() -> None:
    db = MagicMock()
    db.scalars.return_value.first.return_value = "existing-id"
    assert enable_screen_rbac(db, tenant_id=TEST_TENANT_ID) is False
    assert _added(db, TenantSetting) == []


def test_tenant_has_screen_rbac_reads_live_on() -> None:
    db = MagicMock()
    db.scalar.return_value = "row-id"
    assert tenant_has_screen_rbac(db, TEST_TENANT_ID) is True
    db.scalar.return_value = None
    assert tenant_has_screen_rbac(db, TEST_TENANT_ID) is False
