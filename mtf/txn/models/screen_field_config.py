"""SQLAlchemy model — ``txn.screen_field_config``."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    ulid,
    ulid_pk,
)


class ScreenFieldConfig(StandardColumnsMixin, Base):
    """Tenant presentation override of a screen field: display name, order and visibility."""

    __tablename__ = "screen_field_config"
    __table_args__ = (business_unit_fk("screen_field_config"), {"schema": "txn"})

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str] = ulid(TENANT_FK)
    business_unit_id: Mapped[str] = ulid()
    field_id: Mapped[str] = ulid("txn.screen_field.id")
    display_name: Mapped[str | None] = mapped_column(Unicode(150), nullable=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_displayed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
