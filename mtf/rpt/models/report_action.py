"""SQLAlchemy model — `rpt.report_action`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class ReportAction(Base):
    """Toolbar, row, or column action from a report to another report or a screen."""

    __tablename__ = "report_action"
    __table_args__ = {"schema": "rpt"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("rpt.report_definition.id"),
        nullable=False,
    )
    action_key: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(Unicode(150), nullable=False)
    #: CK_report_action_action_type: report | screen
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    #: CK_report_action_display_location: toolbar | row | column
    display_location: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_column_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_report_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("rpt.report_definition.id"),
        nullable=True,
    )
    target_screen_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("txn.screen.id"),
        nullable=True,
    )
    #: CK_report_action_screen_mode: add | view (required when action_type = screen)
    screen_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("10"))

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
