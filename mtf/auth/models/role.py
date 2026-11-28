"""SQLAlchemy model — ``auth.role``."""

from __future__ import annotations

from sqlalchemy import String, Unicode, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    flag,
    ulid,
    ulid_pk,
)


class Role(StandardColumnsMixin, Base):
    """Named bundle of permissions.

    ``tenant_id`` NULL is a platform role (template or system staff); the database then
    requires ``is_system = 1`` and a NULL ``business_unit_id`` (``CK_role_tenant_bu``).
    Tenant roles belong to the tenant's root unit. ``UQ_role_id_user_scope`` is the
    composite-FK target for ``role_permission`` and ``user_role``.
    """

    __tablename__ = "role"
    __table_args__ = (
        UniqueConstraint("id", "user_scope", name="UQ_role_id_user_scope"),
        business_unit_fk("role"),
        # Kept from the dev2 AFTER UPDATE trigger (SQL Server rejects OUTPUT without INTO).
        {"schema": "auth", "implicit_returning": False},
    )

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str | None] = ulid(TENANT_FK, nullable=True)
    business_unit_id: Mapped[str | None] = ulid(nullable=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(Unicode(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Unicode(300), nullable=True)
    #: ``CK_role_user_scope``: system | tenant | tenant_account
    user_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    is_system: Mapped[bool] = flag(default=False)
    #: Only tenant-wide roles may be assigned at the root unit (= all stores).
    is_tenant_wide: Mapped[bool] = flag(default=False)

    def __repr__(self) -> str:
        return (
            f"<Role id={self.id!r} code={self.code!r} tenant_id={self.tenant_id!r} "
            f"user_scope={self.user_scope!r}>"
        )
