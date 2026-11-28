"""SQLAlchemy model — ``auth.user_role``."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    ulid,
    ulid_pk,
)


class UserRole(StandardColumnsMixin, Base):
    """A role held by a user in one place.

    The place is the tenant, the business unit (root = every store) and, for portal
    users, the account. Composite FKs keep the user's scope, the role's scope and this
    row's ``user_scope`` the same; ``CK_user_role_scope_shape`` ties ``tenant_id`` /
    ``business_unit_id`` / ``account_id`` to that scope.
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
        ForeignKeyConstraint(
            ["account_id", "tenant_id"],
            ["tenant.tenant_account.id", "tenant.tenant_account.tenant_id"],
            name="FK_user_role_account_tenant",
        ),
        business_unit_fk("user_role"),
        CheckConstraint(
            "(user_scope = 'system' AND tenant_id IS NULL AND business_unit_id IS NULL"
            " AND account_id IS NULL)"
            " OR (user_scope = 'tenant' AND tenant_id IS NOT NULL"
            " AND business_unit_id IS NOT NULL AND account_id IS NULL)"
            " OR (user_scope = 'tenant_account' AND tenant_id IS NOT NULL"
            " AND business_unit_id IS NOT NULL AND account_id IS NOT NULL)",
            name="CK_user_role_scope_shape",
        ),
        # Kept from the dev2 AFTER INSERT/UPDATE trigger (SQL Server rejects OUTPUT without INTO).
        {"schema": "auth", "implicit_returning": False},
    )

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str | None] = ulid(TENANT_FK, nullable=True)
    business_unit_id: Mapped[str | None] = ulid(nullable=True)
    user_id: Mapped[str] = ulid()
    account_id: Mapped[str | None] = ulid(nullable=True)
    role_id: Mapped[str] = ulid()
    #: ``CK_user_role_user_scope``: system | tenant | tenant_account
    user_scope: Mapped[str] = mapped_column(String(20), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<UserRole id={self.id!r} user_id={self.user_id!r} role_id={self.role_id!r} "
            f"tenant_id={self.tenant_id!r} business_unit_id={self.business_unit_id!r} "
            f"account_id={self.account_id!r}>"
        )
