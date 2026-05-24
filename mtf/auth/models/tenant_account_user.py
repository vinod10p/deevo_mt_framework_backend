"""SQLAlchemy model — `auth.tenant_account_user`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, String, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class TenantAccountUser(Base):
    """Links ``auth.app_user`` (``user_scope=tenant_account``) to ``tenant.tenant_account``."""

    __tablename__ = "tenant_account_user"
    __table_args__ = {"schema": "auth"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(26), ForeignKey("tenant.tenant.id"), nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("tenant.tenant_account.id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(26), ForeignKey("auth.app_user.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'member'"))

    invited_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)
    invited_by: Mapped[str | None] = mapped_column(String(26), ForeignKey("auth.app_user.id"), nullable=True)
    invite_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)

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
    created_by: Mapped[str | None] = mapped_column(String(26), ForeignKey("auth.app_user.id"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(26), ForeignKey("auth.app_user.id"), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(26), ForeignKey("auth.app_user.id"), nullable=True)
