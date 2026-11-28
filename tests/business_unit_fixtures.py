"""Stores and store-level roles for live business unit tests (rows are left for cleanup
by the tenant's deletion, like the rest of a test tenant)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.auth.models.user_role import UserRole
from mtf.shared.database import SessionLocal
from mtf.tenant.business_units import root_unit_id
from mtf.tenant.models.business_unit import BU_TYPE_STORE, BusinessUnit
from tests.cleanup import SEEDED_SYSTEM_USER_ID as BY


def add_stores(tenant_id: str, *codes: str) -> dict[str, str]:
    """Add active stores under the tenant's root, after MAIN; returns their ids by code."""
    with SessionLocal() as db:
        root_id = root_unit_id(db, tenant_id)
        stores = {
            code: BusinessUnit.new(
                by=BY, tenant_id=tenant_id, parent_id=root_id, bu_type=BU_TYPE_STORE,
                code=code, name=code.title(), sort_order=sort_order,
            )
            for sort_order, code in enumerate(codes, start=2)
        }
        db.add_all(stores.values())
        db.commit()
        return {code: unit.id for code, unit in stores.items()}


def grant_store_role(
    tenant_id: str, user_id: str, business_unit_id: str, *permission_codes: str
) -> str:
    """Give ``user_id`` a new custom role, with ``permission_codes``, held at one unit.

    Returns the ``user_role`` id.
    """
    with SessionLocal() as db:
        role = Role.new(
            by=BY,
            tenant_id=tenant_id,
            business_unit_id=root_unit_id(db, tenant_id),
            code=f"store_staff_{uuid.uuid4().hex[:8]}",
            name="Store Staff",
            user_scope="tenant",
        )
        db.add(role)
        db.flush()  # no ORM relationship orders the role before the rows that use it
        permission_ids = db.scalars(
            select(Permission.id).where(
                Permission.code.in_(permission_codes),
                Permission.user_scope == "tenant",
                Permission.is_deleted == False,  # noqa: E712
            )
        ).all()
        assert len(permission_ids) == len(permission_codes), "unknown permission code"
        db.add_all(
            RolePermission.new(
                by=BY, role_id=role.id, permission_id=permission_id, user_scope="tenant"
            )
            for permission_id in permission_ids
        )
        assignment = UserRole.new(
            by=BY, tenant_id=tenant_id, business_unit_id=business_unit_id,
            user_id=user_id, role_id=role.id, user_scope="tenant",
        )
        db.add(assignment)
        db.commit()
        return assignment.id
