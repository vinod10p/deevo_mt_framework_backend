"""SQLAlchemy model — `email.mailbox_credential`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, UnicodeText, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class MailboxCredential(Base):
    """Email mailbox OAuth credentials — table ``email.mailbox_credential``."""

    __tablename__ = "mailbox_credential"
    __table_args__ = {"schema": "email"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(26), nullable=False)
    mailbox_id: Mapped[str] = mapped_column(String(26), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'microsoft_graph'"))
    azure_tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_mode: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'delegated'"))
    credential_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    credential_status: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'active'"))

    access_token: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)
    consented_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)
    last_error: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)

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
    created_by: Mapped[str] = mapped_column(String(26), nullable=False, server_default=text("'01HYSTEM00000000000000000'"))
    updated_by: Mapped[str] = mapped_column(String(26), nullable=False, server_default=text("'01HYSTEM00000000000000000'"))
    deleted_by: Mapped[str | None] = mapped_column(String(26), nullable=True)

