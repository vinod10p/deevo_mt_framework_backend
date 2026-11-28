"""SQLAlchemy model — ``tenant.tenant``."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Unicode, UnicodeText, text
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import StandardColumnsMixin, ulid_pk, utc_timestamp


def _int(default: int, *, nullable: bool = False) -> Mapped[int]:
    return mapped_column(Integer, nullable=nullable, server_default=text(str(default)))


class Tenant(StandardColumnsMixin, Base):
    """A customer organisation (company) — the isolation boundary for all tenant data.

    ``subdomain`` is the company code typed at login (unique). ``status`` and
    ``plan_type`` are constrained in the database (``CK_tenant_status``,
    ``CK_tenant_plan_type``); ``settings`` and ``features_enabled`` must be valid JSON
    when set (``CK_tenant_settings_json``, ``CK_tenant_features_json``).
    """

    __tablename__ = "tenant"
    __table_args__ = {"schema": "tenant"}

    id: Mapped[str] = ulid_pk()
    name: Mapped[str] = mapped_column(Unicode(255), nullable=False)
    subdomain: Mapped[str] = mapped_column(String(100), nullable=False)

    #: ``CK_tenant_status``: pending | expired | cancelled | suspended | trial | active
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'trial'"))
    #: ``CK_tenant_plan_type``: custom | enterprise | professional | starter | trial
    plan_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'trial'")
    )

    #: Stores and other non-root units the plan allows (the root unit is not counted).
    max_business_units: Mapped[int] = _int(1)
    max_users: Mapped[int] = _int(10)
    max_agents: Mapped[int] = _int(5)
    max_contacts: Mapped[int | None] = _int(10000, nullable=True)
    storage_limit_gb: Mapped[int | None] = _int(10, nullable=True)

    subscription_start_date: Mapped[datetime | None] = utc_timestamp(nullable=True)
    subscription_end_date: Mapped[datetime | None] = utc_timestamp(nullable=True)

    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    address_line1: Mapped[str | None] = mapped_column(Unicode(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(Unicode(255), nullable=True)
    city: Mapped[str | None] = mapped_column(Unicode(100), nullable=True)
    state: Mapped[str | None] = mapped_column(Unicode(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: ``CK_tenant_country``: NULL or exactly 2 characters
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    timezone: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'UTC'"))
    locale: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'en-US'"))

    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    settings: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    features_enabled: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)

    def __repr__(self) -> str:
        return f"<Tenant id={self.id!r} name={self.name!r} status={self.status!r}>"
