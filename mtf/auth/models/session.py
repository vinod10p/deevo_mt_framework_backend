"""SQLAlchemy model — ``auth.session`` (login session / refresh rotation row).

The Python class is ``AuthSession`` so callers can keep using ``sqlalchemy.orm.Session``
for the database session type without a name clash.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import LargeBinary, String, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import (
    TENANT_FK,
    RecordStateMixin,
    business_unit_fk,
    ulid,
    ulid_pk,
    utc_timestamp,
)


class AuthSession(RecordStateMixin, Base):
    """Server-side session: access / refresh token hashes, expiry and revocation.

    ``CK_session_tenant_bu``: tenant and portal sessions have ``tenant_id`` and
    ``business_unit_id``; system sessions have neither. ``business_unit_id`` is the unit
    the user is working in and is the source of truth for the current store.
    """

    __tablename__ = "session"
    __table_args__ = (business_unit_fk("session"), {"schema": "auth"})

    id: Mapped[str] = ulid_pk()

    #: Subject user — no FK; resolved through ``auth.app_user`` by every login flow.
    user_id: Mapped[str] = ulid()
    #: ``CK_session_user_type``: system | tenant | tenant_account (the user's ``user_scope``).
    user_type: Mapped[str] = mapped_column(String(20), nullable=False)
    tenant_id: Mapped[str | None] = ulid(TENANT_FK, nullable=True)
    business_unit_id: Mapped[str | None] = ulid(nullable=True)

    #: SHA-256 of the current access JWT (see ``mtf.shared.security.hash_token``).
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    refresh_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)

    #: ``CK_session_auth_method``: password | magic_link | sso | oauth_google |
    #: oauth_microsoft | api_key
    auth_method: Mapped[str] = mapped_column(String(20), nullable=False)
    #: ``CK_session_created_from``: web | mobile_ios | mobile_android | desktop | api
    created_from: Mapped[str] = mapped_column(String(20), nullable=False)

    expires_at: Mapped[datetime] = utc_timestamp()
    refresh_expires_at: Mapped[datetime | None] = utc_timestamp(nullable=True)
    last_activity: Mapped[datetime] = utc_timestamp(default_now=True)

    revoked_at: Mapped[datetime | None] = utc_timestamp(nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Unicode(200), nullable=True)
    #: Who revoked it — no FK; may be staff or another logical principal.
    revoked_by: Mapped[str | None] = ulid(nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Unicode(500), nullable=True)
    device_info: Mapped[str | None] = mapped_column(Unicode(200), nullable=True)

    def __repr__(self) -> str:
        return f"<AuthSession id={self.id!r} user_id={self.user_id!r} active={self.is_active}>"
