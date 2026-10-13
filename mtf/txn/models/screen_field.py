"""SQLAlchemy model — `txn.screen_field`."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

_DT_UTC = DateTime(timezone=False)


class ScreenField(Base):
    """API field on a screen. ``field_key`` is the Pydantic property name, not a DB column."""

    __tablename__ = "screen_field"
    __table_args__ = {"schema": "txn"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    screen_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("txn.screen.id"),
        nullable=False,
    )
    section_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("txn.screen_section.id"),
        nullable=False,
    )
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(Unicode(150), nullable=False)
    #: CK_screen_field_data_type: string | integer | decimal | date | datetime | boolean
    data_type: Mapped[str] = mapped_column(String(20), nullable=False)
    #: CK_screen_field_control_type: text | textarea | number | date | datetime |
    #: dropdown | checkbox | email | phone
    control_type: Mapped[str] = mapped_column(String(20), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("10"))
    #: CK_screen_field_column_span: 1..4
    column_span: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_displayed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    #: CK_screen_field_edit_mode: editable | create_only | readonly
    edit_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'editable'"),
    )
    default_value: Mapped[str | None] = mapped_column(Unicode(500), nullable=True)
    lookup_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("txn.lookup.id"),
        nullable=True,
    )
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 10), nullable=True)
    max_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 10), nullable=True)
    #: CK_screen_field_format_type: decimal | currency | percent | weight
    format_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    help_text: Mapped[str | None] = mapped_column(Unicode(500), nullable=True)

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
