"""User application service."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from ulid import ULID

from mtf.audit.service import AuditSource, audit_insert, audit_update, row_snapshot
from mtf.auth.models import User
from mtf.auth.schemas import UserCreate, UserUpdate
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import conflict, not_found, row_version_conflict
from mtf.shared.security import hash_password


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UserService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_users(self, *, skip: int = 0, limit: int = 100) -> list[User]:
        stmt = (
            select(User)
            .where(User.is_deleted == False)  # noqa: E712
            .order_by(User.email)
            .offset(skip)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def get_user(self, user_id: str) -> User | None:
        stmt = select(User).where(User.id == user_id, User.is_deleted == False)  # noqa: E712
        return self._db.scalars(stmt).first()

    def get_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        stmt = select(User).where(User.email == normalized, User.is_deleted == False)  # noqa: E712
        return self._db.scalars(stmt).first()

    def create_user(
        self,
        data: UserCreate,
        *,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> User:
        normalized = str(data.email).strip().lower()
        existing = self.get_by_email(normalized)
        if existing:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=409,
                detail={"code": "EMAIL_IN_USE", "message": "Email already registered"},
            )

        now = _utc_naive_now()
        user = User(
            id=str(ULID()),
            email=normalized,
            first_name=data.first_name,
            last_name=data.last_name,
            phone=data.phone,
            avatar_url=data.avatar_url,
            auth_provider="local",
        )
        if data.user_scope is not None:
            user.user_scope = data.user_scope
        if data.password:
            user.password_hash = hash_password(data.password)
            user.password_changed_at = now
        self._db.add(user)
        audit_insert(
            self._db,
            entity=user,
            schema_name="auth",
            table_name="app_user",
            actor=actor,
            source=source,
        )
        self._db.commit()
        self._db.refresh(user)
        return user

    def update_user(
        self,
        user_id: str,
        data: UserUpdate,
        *,
        updated_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> User:
        user = self.get_user(user_id)
        if user is None:
            not_found("USER", "User not found")

        if user.row_version != data.row_version:
            row_version_conflict("USER")

        now = _utc_naive_now()
        before = row_snapshot(user)
        updates = data.model_dump(exclude_none=True, exclude={"row_version", "password"})
        if "email" in updates:
            updates["email"] = str(updates["email"]).strip().lower()
            other = self.get_by_email(updates["email"])
            if other is not None and other.id != user_id:
                conflict("USER", "Email already registered")

        for key, value in updates.items():
            setattr(user, key, value)

        if data.password:
            user.password_hash = hash_password(data.password)
            user.password_changed_at = now

        user.updated_at = now
        if updated_by is not None:
            user.updated_by = updated_by

        self._db.add(user)
        audit_update(
            self._db,
            entity=user,
            schema_name="auth",
            table_name="app_user",
            before=before,
            actor=actor,
            source=source,
        )
        self._db.commit()
        self._db.refresh(user)
        return user
