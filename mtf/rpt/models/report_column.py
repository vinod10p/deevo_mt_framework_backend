"""SQLAlchemy model — `rpt.report_column`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class ReportColumn(Base):
    """Grid column metadata — tenant is derived via ``report_id`` (no ``tenant_id`` column)."""

    __tablename__ = "report_column"
    __table_args__ = {"schema": "rpt"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("rpt.report_definition.id"),
        nullable=False,
    )
    column_name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    #: CK_report_column_data_type: string | int | decimal | date | datetime | bool
    data_type: Mapped[str] = mapped_column(String(30), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

    is_displayable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_default_visible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("1"),
    )
    is_sortable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_groupable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    is_filterable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_aggregatable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("0"),
    )
    #: CK_report_column_default_aggregate_type: sum | avg | count | min | max
    default_aggregate_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    display_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_width: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
