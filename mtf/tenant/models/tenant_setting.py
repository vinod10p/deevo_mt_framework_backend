"""SQLAlchemy model — `tenant.tenant_setting`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UnicodeText, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class TenantSetting(Base):
    """Per-tenant key/value setting — table ``tenant.tenant_setting``.

    Live uniqueness is ``(tenant_id, key)`` (``UQ_tenant_setting_tenant_key``).
    ``rbac.screens = on`` is one-way (``TR_tenant_setting_rbac_screens_one_way``).
    """

    __tablename__ = "tenant_setting"
    __table_args__ = (
        # AFTER INSERT/UPDATE/DELETE trigger: SQL Server rejects OUTPUT without INTO.
        {"schema": "tenant", "implicit_returning": False},
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("tenant.tenant.id"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column("key", String(100), nullable=False)
    value: Mapped[str | None] = mapped_column(UnicodeText, nullable=True)

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

    def __repr__(self) -> str:
        return f"<TenantSetting id={self.id!r} tenant_id={self.tenant_id!r} key={self.key!r}>"
