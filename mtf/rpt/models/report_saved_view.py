"""SQLAlchemy model — `rpt.report_saved_view`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Unicode, UnicodeText, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class ReportSavedView(Base):
    """Named criteria + layout for a report, scoped system / tenant / user.

    Clear ``is_default`` in the same write that deactivates or soft-deletes a row —
    ``CK_report_saved_view_default_state`` rejects a default that is inactive or deleted.
    """

    __tablename__ = "report_saved_view"
    __table_args__ = {"schema": "rpt"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    #: CK_report_saved_view_scope: NULL only when scope_type = 'system'.
    tenant_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("tenant.tenant.id"),
        nullable=True,
    )

    report_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("rpt.report_definition.id"),
        nullable=False,
    )
    #: CK_report_saved_view_scope_type: system | tenant | user
    scope_type: Mapped[str] = mapped_column(String(10), nullable=False)
    #: Required only when scope_type = 'user'.
    user_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("auth.app_user.id"),
        nullable=True,
    )
    view_name: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    #: JSON object with a top-level positive int ``version`` (CK_..._criteria_version).
    criteria_json: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    #: JSON object with a top-level positive int ``version`` (CK_..._layout_version).
    layout_json: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

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

    #: Every ORM UPDATE / DELETE is conditional on the loaded ``row_version`` (StaleDataError
    #: when another write got there first); SQL Server generates the new value.
    __mapper_args__ = {"version_id_col": row_version, "version_id_generator": False}
