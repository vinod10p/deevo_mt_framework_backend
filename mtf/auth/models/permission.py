"""SQLAlchemy model — `auth.permission`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Unicode, UniqueConstraint, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class Permission(Base):
    """Catalog of grantable actions — table ``auth.permission``.

    ``code`` is ``<resource_type>.<resource_code>.<action>``.
    ``UQ_permission_id_user_scope`` exists so ``role_permission`` can enforce
    matching ``user_scope`` through a composite foreign key.
    """

    __tablename__ = "permission"
    __table_args__ = (
        UniqueConstraint("id", "user_scope", name="UQ_permission_id_user_scope"),
        {"schema": "auth"},
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    code: Mapped[str] = mapped_column(String(150), nullable=False)
    #: CK_permission_resource_type: menu | screen | api
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_code: Mapped[str] = mapped_column(String(100), nullable=False)
    #: CK_permission_action: view | create | update | delete | export | import | approve
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    #: CK_permission_user_scope: system | tenant | tenant_account
    user_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Unicode(300), nullable=True)

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
        return f"<Permission id={self.id!r} code={self.code!r} user_scope={self.user_scope!r}>"
