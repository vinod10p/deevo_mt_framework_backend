"""SQLAlchemy model — `txn.lookup_column`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class LookupColumn(Base):
    """Column shown or searched in a lookup popup."""

    __tablename__ = "lookup_column"
    __table_args__ = {"schema": "txn"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    lookup_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("txn.lookup.id"),
        nullable=False,
    )
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(Unicode(150), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("10"))
    is_displayed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_searchable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: CK_lookup_column_format_type: decimal | currency | percent | weight
    format_type: Mapped[str | None] = mapped_column(String(30), nullable=True)

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
