"""SQLAlchemy model — `auth.default_role_report`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class DefaultRoleReport(Base):
    """Platform default report grants — table ``auth.default_role_report``.

    Not read at runtime. Copied into ``auth.role_report`` when a tenant is
    created. ``role_id`` must be a platform template role and ``report_id`` a
    system-wide report — those are service rules, not database constraints.
    """

    __tablename__ = "default_role_report"
    __table_args__ = {"schema": "auth"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    role_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("auth.role.id"),
        nullable=False,
    )
    report_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("rpt.report_definition.id"),
        nullable=False,
    )
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    can_export: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

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

    def __repr__(self) -> str:
        return (
            f"<DefaultRoleReport id={self.id!r} role_id={self.role_id!r} "
            f"report_id={self.report_id!r}>"
        )
