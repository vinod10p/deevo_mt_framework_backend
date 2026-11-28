"""SQLAlchemy model — ``auth.app_user``."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Computed, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import StandardColumnsMixin, flag, ulid_pk, utc_timestamp


class User(StandardColumnsMixin, Base):
    """Login identity — one row per person, shared by every tenant they belong to.

    ``user_scope`` (``CK_app_user_user_scope``: system | tenant | tenant_account) decides
    which login flow applies. ``UQ_app_user_id_user_scope`` is the composite-FK target that
    lets ``user_role`` enforce a matching scope.
    """

    __tablename__ = "app_user"
    __table_args__ = (
        UniqueConstraint("id", "user_scope", name="UQ_app_user_id_user_scope"),
        {"schema": "auth"},
    )

    id: Mapped[str] = ulid_pk()

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Persisted computed column (trimmed, lower-case) — maintained by the database.
    email_normalized: Mapped[str | None] = mapped_column(
        String(255), Computed("lower(ltrim(rtrim(email)))", persisted=True)
    )
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_scope: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'tenant'")
    )

    password_hash: Mapped[str | None] = mapped_column(String(500), nullable=True)
    password_changed_at: Mapped[datetime | None] = utc_timestamp(nullable=True)
    auth_provider: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'local'")
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified_at: Mapped[datetime | None] = utc_timestamp(nullable=True)
    last_login_at: Mapped[datetime | None] = utc_timestamp(nullable=True)

    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = utc_timestamp(nullable=True)

    mfa_enabled: Mapped[bool] = flag(default=False)
    mfa_secret_enc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mfa_confirmed_at: Mapped[datetime | None] = utc_timestamp(nullable=True)

    def __repr__(self) -> str:
        return f"<User id={self.id!r} email={self.email!r} user_scope={self.user_scope!r}>"
