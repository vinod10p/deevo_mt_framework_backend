"""SQLAlchemy model — `tenant.tenant`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Unicode, UnicodeText, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

# DATETIME2(3) is timezone-naive wall clock; values are UTC per CONVENTIONS.
_DT_UTC = DateTime(timezone=False)


class Tenant(Base):
    """Organization / workspace row — table ``tenant.tenant``.

    ``subdomain`` is required and unique in the database. ``status`` and
    ``plan_type`` are constrained in the database (see ``CK_tenant_status``,
    ``CK_tenant_plan_type``). ``settings`` and ``features_enabled`` must be
    valid JSON strings when non-null (``CK_tenant_settings_json``,
    ``CK_tenant_features_json``).
    """

    __tablename__ = "tenant"
    __table_args__ = {"schema": "tenant"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(255), nullable=False)
    subdomain: Mapped[str] = mapped_column(String(100), nullable=False)

    #: CK_tenant_status: pending | expired | cancelled | suspended | trial | active
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'trial'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

    #: CK_tenant_plan_type: custom | enterprise | professional | starter | trial
    plan_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'trial'"))
    max_users: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("10"))
    max_agents: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    max_contacts: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default=text("10000"))
    storage_limit_gb: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default=text("10"))

    subscription_start_date: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)
    subscription_end_date: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)

    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    address_line1: Mapped[str | None] = mapped_column(Unicode(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(Unicode(255), nullable=True)
    city: Mapped[str | None] = mapped_column(Unicode(100), nullable=True)
    state: Mapped[str | None] = mapped_column(Unicode(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: CK_tenant_country: NULL or exactly 2 characters
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    timezone: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'UTC'"))
    locale: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'en-US'"))

    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    settings: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    features_enabled: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)

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

    def __repr__(self) -> str:
        return f"<Tenant id={self.id!r} name={self.name!r} status={self.status!r}>"
