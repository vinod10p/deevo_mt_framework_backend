"""SQLAlchemy model — `auth.role_permission`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, String, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class RolePermission(Base):
    """Permission granted by a role — table ``auth.role_permission``.

    Composite FKs on ``(role_id, user_scope)`` and ``(permission_id, user_scope)``
    stop a role from granting a permission of a different scope.
    """

    __tablename__ = "role_permission"
    __table_args__ = (
        ForeignKeyConstraint(
            ["role_id", "user_scope"],
            ["auth.role.id", "auth.role.user_scope"],
            name="FK_role_permission_role_id",
        ),
        ForeignKeyConstraint(
            ["permission_id", "user_scope"],
            ["auth.permission.id", "auth.permission.user_scope"],
            name="FK_role_permission_permission_id",
        ),
        {"schema": "auth"},
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(26), nullable=False)
    permission_id: Mapped[str] = mapped_column(String(26), nullable=False)
    #: CK_role_permission_user_scope: system | tenant | tenant_account
    user_scope: Mapped[str] = mapped_column(String(20), nullable=False)

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
            f"<RolePermission id={self.id!r} role_id={self.role_id!r} "
            f"permission_id={self.permission_id!r}>"
        )
