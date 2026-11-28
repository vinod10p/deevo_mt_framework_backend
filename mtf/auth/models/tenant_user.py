"""SQLAlchemy model — ``auth.tenant_user`` (staff membership of a tenant)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    APP_USER_FK,
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    flag,
    ulid,
    ulid_pk,
    utc_timestamp,
)


class TenantUser(StandardColumnsMixin, Base):
    """Links an ``auth.app_user`` (``user_scope = tenant``) to a tenant.

    Membership is tenant-wide, so ``business_unit_id`` is the tenant's root unit.
    Which stores the user may work in comes from ``auth.user_role``;
    ``default_business_unit_id`` is the store used for members without any role.
    """

    __tablename__ = "tenant_user"
    __table_args__ = (
        business_unit_fk("tenant_user"),
        business_unit_fk(
            "tenant_user",
            "default_business_unit_id",
            name="FK_tenant_user_default_business_unit",
        ),
        {"schema": "auth"},
    )

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str] = ulid(TENANT_FK)
    business_unit_id: Mapped[str] = ulid()
    default_business_unit_id: Mapped[str | None] = ulid(nullable=True)
    user_id: Mapped[str] = ulid(APP_USER_FK)
    #: ``CK_tenant_user_role``: admin | member
    role: Mapped[str] = mapped_column(String(50), nullable=False)

    invited_at: Mapped[datetime | None] = utc_timestamp(nullable=True)
    invited_by: Mapped[str | None] = ulid(APP_USER_FK, nullable=True)
    joined_at: Mapped[datetime | None] = utc_timestamp(nullable=True)

    #: Unused since rbac_fix_05 (members never get a default template); kept for the DDL.
    default_member_role_enabled: Mapped[bool] = flag(default=False)

    def __repr__(self) -> str:
        return (
            f"<TenantUser id={self.id!r} tenant_id={self.tenant_id!r} "
            f"user_id={self.user_id!r} role={self.role!r}>"
        )
