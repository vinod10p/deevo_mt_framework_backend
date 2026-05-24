"""SQLAlchemy model — `auth.tenant_user` (app user ↔ tenant membership)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

# DATETIME2(3) is timezone-naive wall clock; values are UTC per CONVENTIONS.
_DT_UTC = DateTime(timezone=False)


class TenantUser(Base):
    """Membership row linking ``auth.app_user`` to ``tenant.tenant``.

    ``role`` is constrained in the database to
    ``owner`` | ``admin`` | ``member`` | ``viewer`` (see ``CK_tenant_user_role``).
    """

    __tablename__ = "tenant_user"
    __table_args__ = {"schema": "auth"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(26), ForeignKey("tenant.tenant.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(26), ForeignKey("auth.app_user.id"), nullable=False)
    #: CK_tenant_user_role: owner | admin | member | viewer
    role: Mapped[str] = mapped_column(String(50), nullable=False)

    invited_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)
    invited_by: Mapped[str | None] = mapped_column(String(26), ForeignKey("auth.app_user.id"), nullable=True)
    invite_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)

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

    created_by: Mapped[str | None] = mapped_column(String(26), ForeignKey("auth.app_user.id"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(26), ForeignKey("auth.app_user.id"), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(26), ForeignKey("auth.app_user.id"), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<TenantUser id={self.id!r} tenant_id={self.tenant_id!r} "
            f"user_id={self.user_id!r} role={self.role!r}>"
        )
