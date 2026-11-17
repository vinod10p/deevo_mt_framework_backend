"""SQLAlchemy model — `nav.menu_item`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Computed, DateTime, ForeignKey, Integer, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class MenuItem(Base):
    """Submenu row under a module — group (level 1) or report (level 1 or 2)."""

    __tablename__ = "menu_item"
    __table_args__ = {"schema": "nav"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    module_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("nav.menu_module.id"),
        nullable=False,
    )
    parent_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    #: CK_menu_item_item_type: group | report
    item_type: Mapped[str] = mapped_column(String(10), nullable=False)
    label: Mapped[str] = mapped_column(Unicode(100), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    report_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("rpt.report_definition.id"),
        nullable=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

    row_version: Mapped[bytes] = mapped_column(
        ROWVERSION,
        nullable=False,
        server_default=FetchedValue(),
    )
    created_at: Mapped[datetime] = mapped_column(
        _DT_UTC,
        nullable=False,
        server_default=text("sysutcdatetime()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        _DT_UTC,
        nullable=False,
        server_default=text("sysutcdatetime()"),
    )
    created_by: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("auth.app_user.id"),
        nullable=True,
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("auth.app_user.id"),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("auth.app_user.id"),
        nullable=True,
    )
    #: Persisted computed — 'group' when parent_id is set; do not write from Python.
    parent_item_type: Mapped[str | None] = mapped_column(
        String(10),
        Computed(
            "CASE WHEN [parent_id] IS NOT NULL THEN CONVERT(varchar(10), 'group') END",
            persisted=True,
        ),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<MenuItem id={self.id!r} code={self.code!r} item_type={self.item_type!r}>"
        )
