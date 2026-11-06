"""SQLAlchemy models — schema `audit` (v2: sql/audit_schema_v2.sql)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Unicode, UnicodeText, text
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base


class AuditLog(Base):
    """Append-only audit trail — one row per data change or auth event."""

    __tablename__ = "audit_log"
    __table_args__ = {"schema": "audit"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)

    tenant_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    account_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)

    # 'system' | 'tenant' | 'tenant_account'
    user_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    schema_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    table_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    record_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)

    # insert | update | delete | restore | login | login_failed | logout |
    # access_denied | export | import
    action: Mapped[str] = mapped_column(String(20), nullable=False)

    old_values: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    new_values: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)

    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Unicode(500), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Unicode(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("sysutcdatetime()"),
    )
