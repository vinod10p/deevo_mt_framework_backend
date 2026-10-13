"""SQLAlchemy model — `txn.lookup`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class Lookup(Base):
    """Reusable lookup definition. Search APIs themselves are product-owned."""

    __tablename__ = "lookup"
    __table_args__ = {"schema": "txn"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    lookup_key: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(Unicode(150), nullable=False)
    api_base_path: Mapped[str] = mapped_column(String(255), nullable=False)
    return_field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    #: User-visible label column; NULL allowed during migration.
    display_field_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: CK_lookup_min_search_chars: >= 0
    min_search_chars: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    #: CK_lookup_page_size: 1..500
    page_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("50"))

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
