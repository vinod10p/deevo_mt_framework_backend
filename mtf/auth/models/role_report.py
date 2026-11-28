"""SQLAlchemy model — ``auth.role_report``."""

from __future__ import annotations

from sqlalchemy.orm import Mapped

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    flag,
    ulid,
    ulid_pk,
)


class RoleReport(StandardColumnsMixin, Base):
    """Report access granted to a role, owned by one tenant.

    Platform defaults are copied in from ``auth.default_role_report`` at onboarding and
    are not read at runtime. ``can_export`` requires ``can_view``
    (``CK_role_report_export_needs_view``).
    """

    __tablename__ = "role_report"
    __table_args__ = (
        business_unit_fk("role_report"),
        # Kept from the dev2 AFTER INSERT/UPDATE trigger (SQL Server rejects OUTPUT without INTO).
        {"schema": "auth", "implicit_returning": False},
    )

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str] = ulid(TENANT_FK)
    business_unit_id: Mapped[str] = ulid()
    role_id: Mapped[str] = ulid("auth.role.id")
    report_id: Mapped[str] = ulid("rpt.report_definition.id")
    can_view: Mapped[bool] = flag(default=True)
    can_export: Mapped[bool] = flag(default=False)

    def __repr__(self) -> str:
        return (
            f"<RoleReport id={self.id!r} tenant_id={self.tenant_id!r} "
            f"role_id={self.role_id!r} report_id={self.report_id!r}>"
        )
