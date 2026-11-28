"""SQLAlchemy model — ``tenant.tenant_setting``."""

from __future__ import annotations

from sqlalchemy import String, UnicodeText
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    ulid,
    ulid_pk,
)


class TenantSetting(StandardColumnsMixin, Base):
    """Key / value setting of a tenant.

    A row at the root unit is the tenant default; a row at a store overrides it for that
    store. Live uniqueness is ``(tenant_id, business_unit_id, key)``.
    ``rbac.screens = on`` is one-way.
    """

    __tablename__ = "tenant_setting"
    __table_args__ = (
        business_unit_fk("tenant_setting"),
        # Kept from the dev2 AFTER INSERT/UPDATE/DELETE trigger
        # (SQL Server rejects OUTPUT without INTO).
        {"schema": "tenant", "implicit_returning": False},
    )

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str] = ulid(TENANT_FK)
    business_unit_id: Mapped[str] = ulid()
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)

    def __repr__(self) -> str:
        return f"<TenantSetting id={self.id!r} tenant_id={self.tenant_id!r} key={self.key!r}>"
