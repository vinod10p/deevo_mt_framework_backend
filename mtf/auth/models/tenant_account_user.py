"""SQLAlchemy model — ``auth.tenant_account_user`` (portal membership of an account)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKeyConstraint, LargeBinary, String, text
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    APP_USER_FK,
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    ulid,
    ulid_pk,
    utc_timestamp,
)


class TenantAccountUser(StandardColumnsMixin, Base):
    """Links an ``auth.app_user`` (``user_scope = tenant_account``) to a ``tenant.tenant_account``.

    Customer accounts are shared by every store, so ``business_unit_id`` is the root unit.
    """

    __tablename__ = "tenant_account_user"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "tenant_id"],
            ["tenant.tenant_account.id", "tenant.tenant_account.tenant_id"],
            name="FK_tenant_account_user_account_tenant",
        ),
        business_unit_fk("tenant_account_user"),
        {"schema": "auth"},
    )

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str] = ulid(TENANT_FK)
    business_unit_id: Mapped[str] = ulid()
    account_id: Mapped[str] = ulid()
    user_id: Mapped[str] = ulid(APP_USER_FK)
    #: admin | member
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'member'"))

    invited_at: Mapped[datetime | None] = utc_timestamp(nullable=True)
    invited_by: Mapped[str | None] = ulid(APP_USER_FK, nullable=True)
    invite_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    joined_at: Mapped[datetime | None] = utc_timestamp(nullable=True)

    def __repr__(self) -> str:
        return (
            f"<TenantAccountUser id={self.id!r} account_id={self.account_id!r} "
            f"user_id={self.user_id!r} role={self.role!r}>"
        )
