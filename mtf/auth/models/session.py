"""SQLAlchemy model — `auth.session` (login session / refresh rotation row).

Python class is ``AuthSession`` so callers can keep using ``sqlalchemy.orm.Session``
for the DB session type without name clashes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, String, Unicode, text
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import FetchedValue

from mtf.shared.database import Base

# DATETIME2(3) is timezone-naive wall clock; values are UTC per CONVENTIONS.
_DT_UTC = DateTime(timezone=False)


class AuthSession(Base):
    """Server-side session — table ``auth.session`` (access/refresh token hashes, expiry).

    All ``DateTime`` columns use ``timezone=False`` to match SQL Server ``DATETIME2``;
    application code treats stored instants as UTC.
    """

    __tablename__ = "session"
    __table_args__ = {"schema": "auth"}

    id: Mapped[str] = mapped_column(String(26), primary_key=True)

    #: Subject user ULID — **no FK**; resolve via ``auth.app_user`` (all current login flows).
    user_id: Mapped[str] = mapped_column(String(26), nullable=False)
    #: CK_session_user_type: system | tenant | tenant_account (``auth.app_user.user_scope``).
    user_type: Mapped[str] = mapped_column(String(20), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(26), ForeignKey("tenant.tenant.id"), nullable=True)

    #: SHA-256 digest of access JWT (32 bytes) — see ``mtf.shared.security.hash_token``
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    refresh_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)

    #: CK_session_auth_method: password | magic_link | sso | oauth_google | oauth_microsoft | api_key
    auth_method: Mapped[str] = mapped_column(String(20), nullable=False)
    #: CK_session_created_from: web | mobile_ios | mobile_android | desktop | api
    created_from: Mapped[str] = mapped_column(String(20), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(_DT_UTC, nullable=False)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)

    last_activity: Mapped[datetime] = mapped_column(
        _DT_UTC,
        nullable=False,
        server_default=text("sysutcdatetime()"),
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

    revoked_at: Mapped[datetime | None] = mapped_column(_DT_UTC, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Unicode(200), nullable=True)
    #: Actor who revoked (ULID) — **no FK**; may be staff or another logical principal.
    revoked_by: Mapped[str | None] = mapped_column(String(26), nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Unicode(500), nullable=True)
    device_info: Mapped[str | None] = mapped_column(Unicode(200), nullable=True)

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

    def __repr__(self) -> str:
        return f"<AuthSession id={self.id!r} user_id={self.user_id!r} active={self.is_active}>"
