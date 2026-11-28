"""Column building blocks shared by every SQLAlchemy model.

Every table follows the same conventions (``docs/CONVENTIONS.md``):

* ``id`` is an application-generated ULID stored as ``varchar(26)``.
* Times are ``datetime2`` holding UTC wall-clock values (no time zone).
* Rows are never hard-deleted: ``is_deleted`` plus ``deleted_at`` / ``deleted_by``
  (``CK_<table>_deleted`` requires both when ``is_deleted = 1``).
* ``row_version`` is a SQL Server ``rowversion`` for optimistic concurrency.
* ``created_by`` / ``updated_by`` / ``deleted_by`` reference ``auth.app_user``.

Models declare their own business columns and mix in :class:`StandardColumnsMixin`
(or :class:`RecordStateMixin` when the table has no ``created_by`` / ``updated_by``).

Example::

    class TenantSetting(StandardColumnsMixin, Base):
        __tablename__ = "tenant_setting"
        __table_args__ = (business_unit_fk("tenant_setting"), {"schema": "tenant"})

        id: Mapped[str] = ulid_pk()
        tenant_id: Mapped[str] = ulid(TENANT_FK)
        business_unit_id: Mapped[str] = ulid()
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, String, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.clock import utc_now
from mtf.shared.security import generate_id

#: ``datetime2`` without time zone; the application stores and reads UTC.
UtcDateTime = DateTime(timezone=False)

#: Length of a ULID primary or foreign key.
ULID_LENGTH = 26

TENANT_FK = "tenant.tenant.id"
APP_USER_FK = "auth.app_user.id"


def ulid_pk() -> MappedColumn[str]:
    """ULID primary key column."""
    return mapped_column(String(ULID_LENGTH), primary_key=True)


def ulid(foreign_key: str | None = None, *, nullable: bool = False) -> MappedColumn:
    """ULID column, optionally a single-column foreign key (e.g. ``ulid(TENANT_FK)``)."""
    if foreign_key is None:
        return mapped_column(String(ULID_LENGTH), nullable=nullable)
    return mapped_column(String(ULID_LENGTH), ForeignKey(foreign_key), nullable=nullable)


def utc_timestamp(*, nullable: bool = False, default_now: bool = False) -> MappedColumn:
    """UTC ``datetime2`` column; ``default_now`` uses the database clock on insert."""
    if default_now:
        return mapped_column(
            UtcDateTime, nullable=nullable, server_default=text("sysutcdatetime()")
        )
    return mapped_column(UtcDateTime, nullable=nullable)


def flag(*, default: bool) -> MappedColumn[bool]:
    """``bit NOT NULL`` column with a database default."""
    return mapped_column(Boolean, nullable=False, server_default=text("1" if default else "0"))


def business_unit_fk(
    table_name: str,
    column: str = "business_unit_id",
    *,
    name: str | None = None,
) -> ForeignKeyConstraint:
    """Composite FK ``(column, tenant_id)`` → ``tenant.business_unit (id, tenant_id)``.

    Pairing the unit with ``tenant_id`` lets the database guarantee that a row never
    points at another tenant's business unit. Constraint name defaults to
    ``FK_<table>_business_unit`` (the name used in the dev3 DDL).
    """
    return ForeignKeyConstraint(
        [column, "tenant_id"],
        ["tenant.business_unit.id", "tenant.business_unit.tenant_id"],
        name=name or f"FK_{table_name}_business_unit",
    )


class RecordStateMixin:
    """Active / soft-delete flags, ``row_version`` and created / updated / deleted times."""

    is_active: Mapped[bool] = flag(default=True)
    is_deleted: Mapped[bool] = flag(default=False)

    row_version: Mapped[bytes] = mapped_column(
        ROWVERSION, nullable=False, server_default=FetchedValue()
    )

    created_at: Mapped[datetime] = utc_timestamp(default_now=True)
    updated_at: Mapped[datetime] = utc_timestamp(default_now=True)
    deleted_at: Mapped[datetime | None] = utc_timestamp(nullable=True)
    deleted_by: Mapped[str | None] = ulid(APP_USER_FK, nullable=True)

    def mark_deleted(self, by: str, *, at: datetime | None = None) -> datetime:
        """Soft-delete this row (``CK_<table>_deleted`` needs both time and user)."""
        at = at or utc_now()
        self.is_deleted = True
        self.deleted_at = at
        self.deleted_by = by
        self.updated_at = at
        return at


class StandardColumnsMixin(RecordStateMixin):
    """:class:`RecordStateMixin` plus ``created_by`` / ``updated_by`` — most tables."""

    created_by: Mapped[str | None] = ulid(APP_USER_FK, nullable=True)
    updated_by: Mapped[str | None] = ulid(APP_USER_FK, nullable=True)

    @classmethod
    def new(cls, *, by: str | None, **values: Any) -> Self:
        """New row with a fresh ULID ``id``, created and last updated ``by`` one user."""
        return cls(id=generate_id(), created_by=by, updated_by=by, **values)

    def mark_deleted(self, by: str, *, at: datetime | None = None) -> datetime:
        at = super().mark_deleted(by, at=at)
        self.updated_by = by
        return at
