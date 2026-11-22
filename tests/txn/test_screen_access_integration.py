"""Live SQL Server: screen RBAC follows rbac.screens=on, not grants."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from mtf.auth.models.user_role import UserRole
from mtf.shared.database import SessionLocal
from mtf.tenant.models.tenant_setting import TenantSetting
from mtf.tenant.services.rbac_screens import RBAC_SCREENS_KEY, RBAC_SCREENS_ON
from mtf.txn.services.screen_access import tenant_uses_screen_rbac

pytestmark = pytest.mark.integration


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def test_flagged_tenant_uses_screen_rbac_for_any_key() -> None:
    _skip_if_disabled()
    with SessionLocal() as db:
        tenant_id = db.scalars(
            select(TenantSetting.tenant_id).where(
                TenantSetting.key == RBAC_SCREENS_KEY,
                TenantSetting.value == RBAC_SCREENS_ON,
                TenantSetting.is_active == True,  # noqa: E712
                TenantSetting.is_deleted == False,  # noqa: E712
            )
        ).first()
        if tenant_id is None:
            tenant_id = db.scalars(
                select(UserRole.tenant_id).where(
                    UserRole.tenant_id.is_not(None),
                    UserRole.is_active == True,  # noqa: E712
                    UserRole.is_deleted == False,  # noqa: E712
                )
            ).first()
            if tenant_id is None:
                pytest.skip("no live rbac.screens or user_role rows")
            pytest.skip("apply sql/rbac_fix_03_screens_flag.sql first")
        assert tenant_uses_screen_rbac(db, tenant_id, "lead") is True
        assert tenant_uses_screen_rbac(db, tenant_id, "no_such_screen") is True
        assert tenant_uses_screen_rbac(db, "01NOASSIGN0000000000000000", "lead") is False
