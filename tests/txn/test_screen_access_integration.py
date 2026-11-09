"""Live SQL Server: screen RBAC detection after seed + backfill."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from mtf.auth.models.user_role import UserRole
from mtf.shared.database import SessionLocal
from mtf.txn.services.screen_access import tenant_uses_screen_rbac

pytestmark = pytest.mark.integration


def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")


def test_backfilled_tenant_uses_lead_rbac() -> None:
    _skip_if_disabled()
    with SessionLocal() as db:
        tenant_id = db.scalars(
            select(UserRole.tenant_id).where(
                UserRole.tenant_id.is_not(None),
                UserRole.is_active == True,  # noqa: E712
                UserRole.is_deleted == False,  # noqa: E712
            )
        ).first()
        if tenant_id is None:
            pytest.skip("no live user_role rows")
        assert tenant_uses_screen_rbac(db, tenant_id, "lead") is True
        assert tenant_uses_screen_rbac(db, tenant_id, "no_such_screen") is False
        assert (
            tenant_uses_screen_rbac(db, "01NOASSIGN0000000000000000", "lead") is False
        )
