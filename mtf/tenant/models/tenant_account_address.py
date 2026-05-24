"""SQLAlchemy model — `tenant.tenant_account_address`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class TenantAccountAddress(Base):
    """Address row for a tenant account."""

    __tablename__ = "tenant_account_address"
    __table_args__ = {"schema": "tenant"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(26), ForeignKey("tenant.tenant.id"), nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("tenant.tenant_account.id"),
        nullable=False,
    )

    address_type: Mapped[str] = mapped_column(Unicode(50), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

    address_line1: Mapped[str] = mapped_column(Unicode(255), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(Unicode(255), nullable=True)
    city: Mapped[str | None] = mapped_column(Unicode(100), nullable=True)
    state: Mapped[str | None] = mapped_column(Unicode(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

    row_version: Mapped[bytes] = mapped_column(
        ROWVERSION,
        nullable=False,
        server_default=FetchedValue(),
    )
    created_at: Mapped[datetime] = mapped_column(
        _DT_UTC,
        nullable=False,
        server_default=text("sysutcdatetime()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        _DT_UTC,
        nullable=False,
        server_default=text("sysutcdatetime()"),
    )
    created_by: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("auth.app_user.id"),
        nullable=True,
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("auth.app_user.id"),
        nullable=True,
    )
    deleted_by: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("auth.app_user.id"),
        nullable=True,
    )
