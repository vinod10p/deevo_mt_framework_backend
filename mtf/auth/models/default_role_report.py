"""SQLAlchemy model — ``auth.default_role_report``."""

from __future__ import annotations

from sqlalchemy.orm import Mapped

from mtf.shared.database import Base
from mtf.shared.model_columns import StandardColumnsMixin, flag, ulid, ulid_pk


class DefaultRoleReport(StandardColumnsMixin, Base):
    """Platform default report grants, copied into ``auth.role_report`` for each new tenant.

    Not read at runtime. ``role_id`` must be a platform template role and ``report_id`` a
    system-wide report.
    """

    __tablename__ = "default_role_report"
    __table_args__ = (
        # Kept from the dev2 AFTER INSERT/UPDATE trigger (SQL Server rejects OUTPUT without INTO).
        {"schema": "auth", "implicit_returning": False},
    )

    id: Mapped[str] = ulid_pk()
    role_id: Mapped[str] = ulid("auth.role.id")
    report_id: Mapped[str] = ulid("rpt.report_definition.id")
    can_view: Mapped[bool] = flag(default=True)
    can_export: Mapped[bool] = flag(default=False)

    def __repr__(self) -> str:
        return (
            f"<DefaultRoleReport id={self.id!r} role_id={self.role_id!r} "
            f"report_id={self.report_id!r}>"
        )
