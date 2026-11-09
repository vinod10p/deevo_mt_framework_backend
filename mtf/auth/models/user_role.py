"""SQLAlchemy model — `auth.user_role`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    text,
)
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class UserRole(Base):
    """Role assignment for a user in one place — table ``auth.user_role``.

    Composite FKs keep the user's scope, the role's scope, and this row's
    ``user_scope`` the same. ``CK_user_role_scope_shape`` ties ``tenant_id`` /
    ``account_id`` to that scope.
    """

    __tablename__ = "user_role"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "user_scope"],
            ["auth.app_user.id", "auth.app_user.user_scope"],
            name="FK_user_role_user_id",
        ),
        ForeignKeyConstraint(
            ["role_id", "user_scope"],
            ["auth.role.id", "auth.role.user_scope"],
            name="FK_user_role_role_id",
        ),
        CheckConstraint(
            "("
            "(user_scope = 'system' AND tenant_id IS NULL AND account_id IS NULL) OR "
            "(user_scope = 'tenant' AND tenant_id IS NOT NULL AND account_id IS NULL) OR "
            "(user_scope = 'tenant_account' AND tenant_id IS NOT NULL AND account_id IS NOT NULL)"
            ")",
            name="CK_user_role_scope_shape",
        ),
        {"schema": "auth"},
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("tenant.tenant.id"),
        nullable=True,
    )
    user_id: Mapped[str] = mapped_column(String(26), nullable=False)
    account_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("tenant.tenant_account.id"),
        nullable=True,
    )
    role_id: Mapped[str] = mapped_column(String(26), nullable=False)
    #: CK_user_role_user_scope: system | tenant | tenant_account
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
            f"<UserRole id={self.id!r} user_id={self.user_id!r} role_id={self.role_id!r} "
            f"tenant_id={self.tenant_id!r} account_id={self.account_id!r}>"
        )
