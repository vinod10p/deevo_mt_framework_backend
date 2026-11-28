"""SQLAlchemy model — ``auth.role_permission``."""

from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import StandardColumnsMixin, ulid, ulid_pk


class RolePermission(StandardColumnsMixin, Base):
    """A permission granted by a role.

    Composite FKs on ``(role_id, user_scope)`` and ``(permission_id, user_scope)`` stop a
    role from granting a permission of a different scope.
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

    id: Mapped[str] = ulid_pk()
    role_id: Mapped[str] = ulid()
    permission_id: Mapped[str] = ulid()
    #: ``CK_role_permission_user_scope``: system | tenant | tenant_account
    user_scope: Mapped[str] = mapped_column(String(20), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<RolePermission id={self.id!r} role_id={self.role_id!r} "
            f"permission_id={self.permission_id!r}>"
        )
