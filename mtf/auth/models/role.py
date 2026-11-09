"""SQLAlchemy model — `auth.role`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Unicode, UniqueConstraint, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class Role(Base):
    """Named bundle of permissions — table ``auth.role``.

    ``tenant_id`` NULL is a platform role (template or system staff) and the
    database requires ``is_system = 1``. ``UQ_role_id_user_scope`` is the
    composite-FK target for ``role_permission`` and ``user_role``.
    """

    __tablename__ = "role"
    __table_args__ = (
        UniqueConstraint("id", "user_scope", name="UQ_role_id_user_scope"),
        {"schema": "auth"},
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("tenant.tenant.id"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(Unicode(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Unicode(300), nullable=True)
    #: CK_role_user_scope: system | tenant | tenant_account
    user_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

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
            f"<Role id={self.id!r} code={self.code!r} tenant_id={self.tenant_id!r} "
            f"user_scope={self.user_scope!r}>"
        )
