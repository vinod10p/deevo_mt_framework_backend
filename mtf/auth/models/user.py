"""SQLAlchemy model — `auth.app_user`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base


class User(Base):
    """Application login identity — table `auth.app_user`."""

    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("id", "user_scope", name="UQ_app_user_id_user_scope"),
        {"schema": "auth"},
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(500), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    auth_provider: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'local'"))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    mfa_secret_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mfa_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    row_version: Mapped[bytes] = mapped_column(
        ROWVERSION,
        nullable=False,
        server_default=FetchedValue(),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("sysutcdatetime()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
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

    #: Persisted computed column — DB-maintained; do not set from Python.
    email_normalized: Mapped[str] = mapped_column(
        String(255),
        Computed("lower(ltrim(rtrim(email)))", persisted=True),
    )

    #: CK_app_user_user_scope: system | tenant | tenant_account
    user_scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'tenant'"))

    deleted_by: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("auth.app_user.id"),
        nullable=True,
    )
