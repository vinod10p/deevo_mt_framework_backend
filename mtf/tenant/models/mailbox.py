"""SQLAlchemy model — `email.mailbox`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class Mailbox(Base):
    """Email mailbox row — table ``email.mailbox``."""

    __tablename__ = "mailbox"
    __table_args__ = {"schema": "email"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(26), nullable=False)
    email_address: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_email: Mapped[str | None] = mapped_column(
        String(255),
        server_default=FetchedValue(),
        nullable=True,
    )
    display_name: Mapped[str | None] = mapped_column(Unicode(255), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'microsoft_graph'"))
    graph_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mailbox_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'user'"))
    is_sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    trans_flag: Mapped[str | None] = mapped_column(String(10), nullable=True, server_default=text("'A'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

    row_version: Mapped[bytes] = mapped_column(
        ROWVERSION,
        server_default=FetchedValue(),
        server_onupdate=FetchedValue(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(_DT_UTC, nullable=False, server_default=text("SYSUTCDATETIME()"))
    updated_at: Mapped[datetime] = mapped_column(_DT_UTC, nullable=False, server_default=text("SYSUTCDATETIME()"))
    deleted_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(26), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(26), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(26), nullable=True)
