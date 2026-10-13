"""SQLAlchemy model — `txn.screen`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class Screen(Base):
    """System-level transaction screen definition — no tenant_id."""

    __tablename__ = "screen"
    __table_args__ = {"schema": "txn"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    screen_key: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(Unicode(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Unicode(500), nullable=True)
    api_base_path: Mapped[str] = mapped_column(String(255), nullable=False)
    #: CK_screen_layout_type: standard | tabs
    layout_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'standard'"),
    )
    #: CK_screen_permission_mode: open | restricted
    permission_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'open'"),
    )

    allow_view: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    allow_add: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    allow_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    allow_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

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
    deleted_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("auth.app_user.id"),
        nullable=True,
    )
