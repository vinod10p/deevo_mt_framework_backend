"""SQLAlchemy model — `auth.role_report`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class RoleReport(Base):
    """Per-tenant report grant for a role — table ``auth.role_report``.

    Every row belongs to a tenant. Platform defaults are copied in from
    ``auth.default_role_report`` at onboarding, not read at runtime.
    ``can_export`` requires ``can_view`` (``CK_role_report_export_needs_view``).
    """

    __tablename__ = "role_report"
    __table_args__ = {"schema": "auth"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("tenant.tenant.id"),
        nullable=False,
    )
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
            f"<RoleReport id={self.id!r} tenant_id={self.tenant_id!r} "
            f"role_id={self.role_id!r} report_id={self.report_id!r}>"
        )
