"""SQLAlchemy model — ``txn.screen_permission``."""

from __future__ import annotations

from sqlalchemy.orm import Mapped

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    APP_USER_FK,
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    flag,
    ulid,
    ulid_pk,
)


class ScreenPermission(StandardColumnsMixin, Base):
    """Per-user screen access in one tenant (legacy gate for tenants without RBAC screens).

    Inactive rows deny; deleted rows are ignored.
    """

    __tablename__ = "screen_permission"
    __table_args__ = (business_unit_fk("screen_permission"), {"schema": "txn"})

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str] = ulid(TENANT_FK)
    business_unit_id: Mapped[str] = ulid()
    user_id: Mapped[str] = ulid(APP_USER_FK)
    screen_id: Mapped[str] = ulid("txn.screen.id")
    can_access: Mapped[bool] = flag(default=False)
    can_view: Mapped[bool] = flag(default=False)
    can_add: Mapped[bool] = flag(default=False)
    can_edit: Mapped[bool] = flag(default=False)
    can_delete: Mapped[bool] = flag(default=False)
