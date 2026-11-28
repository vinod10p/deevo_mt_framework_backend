"""SQLAlchemy models — schema ``audit`` (``sql/audit_schema_v2.sql`` + business unit)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Unicode, UnicodeText
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import ulid, ulid_pk, utc_timestamp


class AuditLog(Base):
    """Append-only audit trail — one row per data change or auth event.

    No foreign keys: the log must outlive the rows it describes.
    ``CK_audit_log_tenant_bu``: ``business_unit_id`` is set exactly when ``tenant_id`` is.
    """

    __tablename__ = "audit_log"
    __table_args__ = {"schema": "audit"}

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str | None] = ulid(nullable=True)
    business_unit_id: Mapped[str | None] = ulid(nullable=True)
    account_id: Mapped[str | None] = ulid(nullable=True)
    session_id: Mapped[str | None] = ulid(nullable=True)
    request_id: Mapped[str | None] = ulid(nullable=True)
    user_id: Mapped[str | None] = ulid(nullable=True)
    #: system | tenant | tenant_account
    user_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    schema_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    table_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    record_id: Mapped[str | None] = ulid(nullable=True)
    #: insert | update | delete | restore | login | login_failed | logout |
    #: access_denied | export | import | …
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    old_values: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    new_values: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Unicode(500), nullable=True)
    reason: Mapped[str | None] = mapped_column(Unicode(500), nullable=True)
    created_at: Mapped[datetime] = utc_timestamp(default_now=True)
