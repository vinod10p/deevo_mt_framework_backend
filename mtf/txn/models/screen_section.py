"""SQLAlchemy model — `txn.screen_section`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class ScreenSection(Base):
    """Field group on a screen — stacked (standard) or tabbed (tabs)."""

    __tablename__ = "screen_section"
    __table_args__ = {"schema": "txn"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    screen_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("txn.screen.id"),
        nullable=False,
    )
    section_key: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(Unicode(150), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("10"))
    #: CK_screen_section_column_count: 1..4
    column_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_collapsible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    #: CK_screen_section_collapsed: is_collapsed_default requires is_collapsible
    is_collapsed_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("0"),
    )

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
