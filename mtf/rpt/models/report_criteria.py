"""SQLAlchemy model — `rpt.report_criteria`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class ReportCriteria(Base):
    """Pre-run filter panel field — tenant is derived via ``report_id`` (no ``tenant_id``)."""

    __tablename__ = "report_criteria"
    __table_args__ = {"schema": "rpt"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("rpt.report_definition.id"),
        nullable=False,
    )
    criteria_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    #: CK_report_criteria_data_type: string | int | decimal | date | datetime | bool
    data_type: Mapped[str] = mapped_column(String(30), nullable=False)
    #: CK_report_criteria_control_type:
    #: text | number | date | daterange | dropdown | multiselect | bool
    control_type: Mapped[str] = mapped_column(String(30), nullable=False)
    #: Must return exactly two columns named ``value`` and ``label``.
    lookup_proc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    default_value: Mapped[str | None] = mapped_column(Unicode(500), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

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
