"""SQLAlchemy model — ``rpt.report_saved_view``."""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, Unicode, UnicodeText
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

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


class ReportSavedView(StandardColumnsMixin, Base):
    """Named criteria + layout for a report, scoped ``system`` / ``tenant`` / ``user``.

    ``CK_report_saved_view_scope``: ``system`` views have no tenant, business unit or user;
    ``tenant`` views have a tenant and unit; ``user`` views also have a user.
    Clear ``is_default`` in the same write that deactivates or soft-deletes a row —
    ``CK_report_saved_view_default_state`` rejects a default that is inactive or deleted.
    """

    __tablename__ = "report_saved_view"
    __table_args__ = (business_unit_fk("report_saved_view"), {"schema": "rpt"})

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str | None] = ulid(TENANT_FK, nullable=True)
    business_unit_id: Mapped[str | None] = ulid(nullable=True)
    report_id: Mapped[str] = ulid("rpt.report_definition.id")
    #: ``CK_report_saved_view_scope_type``: system | tenant | user
    scope_type: Mapped[str] = mapped_column(String(10), nullable=False)
    #: Required only when ``scope_type = 'user'``.
    user_id: Mapped[str | None] = ulid(APP_USER_FK, nullable=True)
    view_name: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    #: JSON object with a top-level positive int ``version`` (``CK_..._criteria_version``).
    criteria_json: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    #: JSON object with a top-level positive int ``version`` (``CK_..._layout_version``).
    layout_json: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    is_default: Mapped[bool] = flag(default=False)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        # Every ORM UPDATE / DELETE is conditional on the loaded ``row_version``
        # (StaleDataError when another write got there first); SQL Server generates it.
        return {"version_id_col": cls.__table__.c.row_version, "version_id_generator": False}
