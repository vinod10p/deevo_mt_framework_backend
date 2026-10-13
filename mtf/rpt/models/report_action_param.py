"""SQLAlchemy model — `rpt.report_action_param`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class ReportActionParam(Base):
    """Maps a source report column or criterion into a target key."""

    __tablename__ = "report_action_param"
    __table_args__ = {"schema": "rpt"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    action_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("rpt.report_action.id"),
        nullable=False,
    )
    #: CK_report_action_param_source_type: column | criteria
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_key: Mapped[str] = mapped_column(String(100), nullable=False)
    target_key: Mapped[str] = mapped_column(String(100), nullable=False)

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
