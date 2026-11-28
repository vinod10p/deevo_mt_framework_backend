"""SQLAlchemy model — ``tenant.tenant_account_address``."""

from __future__ import annotations

from sqlalchemy import String, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    flag,
    ulid,
    ulid_pk,
)


class TenantAccountAddress(StandardColumnsMixin, Base):
    """An address of a tenant account; ``business_unit_id`` matches its account (root)."""

    __tablename__ = "tenant_account_address"
    __table_args__ = (business_unit_fk("tenant_account_address"), {"schema": "tenant"})

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str] = ulid(TENANT_FK)
    business_unit_id: Mapped[str] = ulid()
    account_id: Mapped[str] = ulid("tenant.tenant_account.id")
    address_type: Mapped[str] = mapped_column(Unicode(50), nullable=False)
    is_default: Mapped[bool] = flag(default=False)
    address_line1: Mapped[str] = mapped_column(Unicode(255), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(Unicode(255), nullable=True)
    city: Mapped[str | None] = mapped_column(Unicode(100), nullable=True)
    state: Mapped[str | None] = mapped_column(Unicode(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<TenantAccountAddress id={self.id!r} account_id={self.account_id!r} "
            f"address_type={self.address_type!r}>"
        )
