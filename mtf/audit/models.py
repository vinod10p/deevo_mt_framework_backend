"""SQLAlchemy models — schema `audit`."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, UnicodeText, text
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base


class AuditLog(Base):
    """Immutable audit trail entry for every significant data change or auth event."""

    __tablename__ = "audit_log"
    __table_args__ = {"schema": "audit"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)

    tenant_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)

    # 'app_user' | 'customer_user'
    user_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    schema_name: Mapped[str] = mapped_column(String(50), nullable=False)
    table_name: Mapped[str] = mapped_column(String(100), nullable=False)
    record_id: Mapped[str] = mapped_column(String(26), nullable=False)

    # 'insert' | 'update' | 'delete' | 'login' | 'logout' | 'export' | 'import'
    action: Mapped[str] = mapped_column(String(20), nullable=False)

    old_values: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    new_values: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)

    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("sysutcdatetime()"),
    )
