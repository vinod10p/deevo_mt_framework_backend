"""SQLAlchemy model — ``tenant.business_unit``."""

from __future__ import annotations

from typing import Final

from sqlalchemy import CHAR, Integer, String, Unicode, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    ulid,
    ulid_pk,
)

#: ``CK_business_unit_bu_type``. Logic must branch on ``bu_type``, never on code or name.
BU_TYPE_ROOT: Final = "root"
BU_TYPE_STORE: Final = "store"
BU_TYPES: Final = frozenset({BU_TYPE_ROOT, BU_TYPE_STORE, "warehouse", "workshop", "online"})


class BusinessUnit(StandardColumnsMixin, Base):
    """A store, warehouse, workshop or online shop of one tenant — or the tenant's root.

    Each tenant has exactly one ``root`` unit (``UQ_business_unit_root``), which owns
    tenant-wide data and has no parent; every other unit has a parent in the same tenant
    (``CK_business_unit_root_parent``, ``FK_business_unit_parent``).
    Design: ``sql/business_unit_database_design.md``.
    """

    __tablename__ = "business_unit"
    __table_args__ = (
        # Composite target for every ``(business_unit_id, tenant_id)`` foreign key.
        UniqueConstraint("id", "tenant_id", name="UQ_business_unit_id_tenant"),
        business_unit_fk("business_unit", "parent_id", name="FK_business_unit_parent"),
        {"schema": "tenant"},
    )

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str] = ulid(TENANT_FK)
    #: NULL only for the root unit.
    parent_id: Mapped[str | None] = ulid(nullable=True)

    bu_type: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Typed by users at login; unique per tenant among live units, matched case-insensitively.
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(Unicode(255), nullable=False)

    address_line1: Mapped[str | None] = mapped_column(Unicode(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(Unicode(255), nullable=True)
    city: Mapped[str | None] = mapped_column(Unicode(100), nullable=True)
    state: Mapped[str | None] = mapped_column(Unicode(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    #: NULL = use the tenant's timezone.
    timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: ISO 4217 code; NULL = use the tenant's currency.
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    @property
    def is_root(self) -> bool:
        return self.bu_type == BU_TYPE_ROOT

    def __repr__(self) -> str:
        return (
            f"<BusinessUnit id={self.id!r} tenant_id={self.tenant_id!r} "
            f"bu_type={self.bu_type!r} code={self.code!r}>"
        )
