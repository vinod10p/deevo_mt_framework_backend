"""SQLAlchemy model — `rpt.report_definition`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class ReportDefinition(Base):
    """Report registry — one row per report (system-wide or tenant-owned)."""

    __tablename__ = "report_definition"
    __table_args__ = {"schema": "rpt"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    #: CK_report_definition_scope: NULL only when scope_type = 'system'.
    tenant_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("tenant.tenant.id"),
        nullable=True,
    )

    #: CK_report_definition_scope_type: system | tenant
    scope_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=text("'tenant'"),
    )
    report_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    proc_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Unicode(500), nullable=True)
    default_max_rows: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("20000"),
    )
    #: CK_report_definition_permission_mode: open | restricted
    permission_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'open'"),
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
    deleted_by: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("auth.app_user.id"),
        nullable=True,
    )
