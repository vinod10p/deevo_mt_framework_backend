"""One-way tenant flag that fail-closes screen gates onto RBAC."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.tenant.business_units import root_unit_id
from mtf.tenant.models.tenant_setting import TenantSetting

RBAC_SCREENS_KEY = "rbac.screens"
RBAC_SCREENS_ON = "on"


def tenant_has_screen_rbac(db: Session, tenant_id: str) -> bool:
    """True when this tenant has live ``rbac.screens = on``."""
    return db.scalar(
        select(TenantSetting.id)
        .where(
            TenantSetting.tenant_id == tenant_id,
            TenantSetting.key == RBAC_SCREENS_KEY,
            TenantSetting.value == RBAC_SCREENS_ON,
            TenantSetting.is_active == True,  # noqa: E712
            TenantSetting.is_deleted == False,  # noqa: E712
        )
        .limit(1)
    ) is not None


def enable_screen_rbac(
    db: Session,
    *,
    tenant_id: str,
    created_by: str | None = None,
) -> bool:
    """Insert ``rbac.screens = on`` if this tenant does not already have it.

    Returns True when a row was added. Never turns the flag off.
    """
    existing = db.scalars(
        select(TenantSetting.id).where(
            TenantSetting.tenant_id == tenant_id,
            TenantSetting.key == RBAC_SCREENS_KEY,
            TenantSetting.is_deleted == False,  # noqa: E712
        )
    ).first()
    if existing is not None:
        return False
    db.add(
        TenantSetting.new(
            by=created_by,
            tenant_id=tenant_id,
            business_unit_id=root_unit_id(db, tenant_id),
            key=RBAC_SCREENS_KEY,
            value=RBAC_SCREENS_ON,
        )
    )
    return True
