"""A tenant's default business units: the root (tenant-wide data) and its first store.

Every tenant has exactly one root unit and at least one store (onboarding creates both).
Lookups use ``bu_type`` and ``sort_order`` only — codes and names belong to the tenant
and may be renamed. A tenant's root id never changes, so it is cached per process.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.shared.exceptions import conflict
from mtf.tenant.models.business_unit import BU_TYPE_ROOT, BU_TYPE_STORE, BusinessUnit
from mtf.tenant.models.tenant import Tenant

#: Codes given to the units created at onboarding; tenants may rename them.
ROOT_UNIT_CODE = "COMPANY"
FIRST_STORE_CODE = "MAIN"
FIRST_STORE_NAME = "Main Store"

_root_ids: dict[str, str] = {}
_ADDRESS_FIELDS = ("address_line1", "address_line2", "city", "state", "postal_code", "country")


def root_unit_id(db: Session, tenant_id: str) -> str:
    """Id of the tenant's root unit (owner of tenant-wide rows)."""
    if tenant_id not in _root_ids:
        _root_ids[tenant_id] = _required_unit_id(
            db, tenant_id, BusinessUnit.bu_type == BU_TYPE_ROOT
        )
    return _root_ids[tenant_id]


def first_store_id(db: Session, tenant_id: str) -> str:
    """Id of the tenant's first active store — the default store for new staff."""
    return _required_unit_id(
        db,
        tenant_id,
        BusinessUnit.bu_type == BU_TYPE_STORE,
        BusinessUnit.is_active == True,  # noqa: E712
    )


def membership_units(db: Session, tenant_id: str) -> dict[str, str]:
    """Unit columns of a new staff membership: tenant-wide (root), default store first."""
    return {
        "business_unit_id": root_unit_id(db, tenant_id),
        "default_business_unit_id": first_store_id(db, tenant_id),
    }


def create_default_units(
    db: Session, tenant: Tenant, *, created_by: str | None
) -> tuple[BusinessUnit, BusinessUnit]:
    """Add the root unit and the first store for a new tenant (caller commits)."""
    common = {
        "tenant_id": tenant.id,
        "timezone": tenant.timezone,
        **{field: getattr(tenant, field) for field in _ADDRESS_FIELDS},
    }
    root = BusinessUnit.new(
        by=created_by,
        bu_type=BU_TYPE_ROOT,
        code=ROOT_UNIT_CODE,
        name=tenant.name,
        sort_order=0,
        **common,
    )
    store = BusinessUnit.new(
        by=created_by,
        parent_id=root.id,
        bu_type=BU_TYPE_STORE,
        code=FIRST_STORE_CODE,
        name=FIRST_STORE_NAME,
        sort_order=1,
        **common,
    )
    db.add_all([root, store])
    # Insert now: rows that reference a unit (role reports, settings, …) have no ORM
    # relationship to it, so the unit of work would not order them after the units.
    db.flush([root, store])
    _root_ids[tenant.id] = root.id
    return root, store


def _required_unit_id(db: Session, tenant_id: str, *conditions: object) -> str:
    unit_id = db.scalars(
        select(BusinessUnit.id)
        .where(
            BusinessUnit.tenant_id == tenant_id,
            BusinessUnit.is_deleted == False,  # noqa: E712
            *conditions,
        )
        .order_by(BusinessUnit.sort_order, BusinessUnit.created_at)
        .limit(1)
    ).first()
    if unit_id is None:
        conflict("TENANT_BUSINESS_UNIT", "The tenant has no matching business unit")
    return unit_id
