"""Tidy up rows created by integration tests — soft-deleted, the way the app removes data."""

from __future__ import annotations

from sqlalchemy import select

from mtf.auth.models.role import Role
from mtf.auth.models.user import User
from mtf.shared.database import SessionLocal
from mtf.tenant.models.tenant import Tenant

#: Seeded platform system user; recorded as the actor of test clean-up.
SEEDED_SYSTEM_USER_ID = "01HYSTEM00000000000000000"


def soft_delete_users(*user_ids: str) -> None:
    """Deactivate and soft-delete the given ``auth.app_user`` rows (missing ids are ignored)."""
    with SessionLocal() as db:
        for user in db.scalars(select(User).where(User.id.in_(user_ids))):
            user.is_active = False
            user.mark_deleted(SEEDED_SYSTEM_USER_ID)
        db.commit()


def soft_delete_tenants(*tenant_ids: str) -> None:
    """Soft-delete the given test tenants straight in the database.

    No API call: a teardown must not depend on whatever auth override is (or isn't) still
    installed, and must fail loudly rather than leave live test tenants behind.
    """
    with SessionLocal() as db:
        tenants = list(db.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids))))
        assert len(tenants) == len(set(tenant_ids)), "unknown test tenant id"
        for tenant in tenants:
            if not tenant.is_deleted:
                tenant.is_active = False
                tenant.mark_deleted(SEEDED_SYSTEM_USER_ID)
        db.commit()


def soft_delete_tenant_roles(tenant_id: str) -> None:
    """Soft-delete every live custom role a test created in ``tenant_id``."""
    with SessionLocal() as db:
        roles = select(Role).where(Role.tenant_id == tenant_id, Role.is_deleted == False)  # noqa: E712
        for role in db.scalars(roles):
            role.mark_deleted(SEEDED_SYSTEM_USER_ID)
        db.commit()
