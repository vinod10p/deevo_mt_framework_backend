"""SQLAlchemy model — ``tenant.tenant_account``."""

from __future__ import annotations

from sqlalchemy import String, Unicode, UnicodeText, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    ulid,
    ulid_pk,
)


class TenantAccount(StandardColumnsMixin, Base):
    """An account under a tenant (customer, vendor, employee, …).

    Accounts are shared by every store, so ``business_unit_id`` is the root unit.
    """

    __tablename__ = "tenant_account"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="UQ_tenant_account_id_tenant_id"),
        business_unit_fk("tenant_account"),
        {"schema": "tenant"},
    )

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str] = ulid(TENANT_FK)
    business_unit_id: Mapped[str] = ulid()
    account_code: Mapped[str] = mapped_column(String(26), nullable=False)
    account_type: Mapped[str] = mapped_column(Unicode(50), nullable=False)
    name: Mapped[str] = mapped_column(Unicode(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    custom_fields: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))

    def __repr__(self) -> str:
        return (
            f"<TenantAccount id={self.id!r} tenant_id={self.tenant_id!r} "
            f"account_code={self.account_code!r}>"
        )
