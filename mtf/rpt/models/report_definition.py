"""SQLAlchemy model — ``rpt.report_definition``."""

from __future__ import annotations

from sqlalchemy import Integer, String, Unicode, text
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    TENANT_FK,
    StandardColumnsMixin,
    business_unit_fk,
    ulid,
    ulid_pk,
)


class ReportDefinition(StandardColumnsMixin, Base):
    """Report registry — one row per report, platform-wide or owned by a tenant.

    ``CK_report_definition_scope``: ``system`` reports have no tenant and no business
    unit; ``tenant`` reports have both (the root unit).
    """

    __tablename__ = "report_definition"
    __table_args__ = (
        business_unit_fk("report_definition"),
        # Kept from the dev2 AFTER UPDATE trigger (SQL Server rejects OUTPUT without INTO).
        {"schema": "rpt", "implicit_returning": False},
    )

    id: Mapped[str] = ulid_pk()
    tenant_id: Mapped[str | None] = ulid(TENANT_FK, nullable=True)
    business_unit_id: Mapped[str | None] = ulid(nullable=True)
    #: ``CK_report_definition_scope_type``: system | tenant
    scope_type: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'tenant'")
    )
    report_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(Unicode(200), nullable=False)
    proc_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Unicode(500), nullable=True)
    default_max_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("20000")
    )
    #: ``CK_report_definition_permission_mode``: open | restricted
    permission_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'open'")
    )
