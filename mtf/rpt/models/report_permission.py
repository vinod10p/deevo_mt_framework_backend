"""SQLAlchemy model — `rpt.report_permission`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class ReportPermission(Base):
    """Per-user report access for one tenant. Not wired to V1 endpoints yet."""

    __tablename__ = "report_permission"
    __table_args__ = {"schema": "rpt"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("tenant.tenant.id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("auth.app_user.id"),
        nullable=False,
    )
    report_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("rpt.report_definition.id"),
        nullable=False,
    )
    can_access: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

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
