"""Tenant account membership service — `auth.tenant_account_user`."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mtf.audit.service import (
    AuditSource,
    audit_insert,
    audit_soft_delete,
    audit_update,
    row_snapshot,
)
from mtf.auth.models.tenant_account_user import TenantAccountUser
from mtf.auth.models.user import User
from mtf.shared.db_integrity import is_unique_constraint_violation
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import bad_request, conflict, forbidden, not_found, row_version_conflict
from mtf.shared.security import generate_id, hash_password
from mtf.tenant.models import TenantAccount


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TenantAccountUserService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def _require_account(self, tenant_id: str, account_id: str) -> TenantAccount:
        row = self._db.scalars(
            select(TenantAccount).where(
                TenantAccount.id == account_id,
                TenantAccount.tenant_id == tenant_id,
                TenantAccount.is_deleted == False,  # noqa: E712
            )
        ).first()
        if row is None:
            not_found("TENANT_ACCOUNT", "Account not found")
        return row

    def _get_user_any(self, user_id: str) -> User | None:
        return self._db.scalars(select(User).where(User.id == user_id).limit(1)).first()

    def _get_active_user_by_email(self, email_norm: str) -> User | None:
        stmt = (
            select(User)
            .where(
                User.email_normalized == email_norm,
                User.is_deleted == False,  # noqa: E712
            )
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def _membership(
        self,
        tenant_id: str,
        account_id: str,
        user_id: str,
        *,
        include_deleted: bool = False,
    ) -> TenantAccountUser | None:
        filters = [
            TenantAccountUser.tenant_id == tenant_id,
            TenantAccountUser.account_id == account_id,
            TenantAccountUser.user_id == user_id,
        ]
        if not include_deleted:
            filters.append(TenantAccountUser.is_deleted == False)  # noqa: E712
        return self._db.scalars(select(TenantAccountUser).where(*filters).limit(1)).first()

    def _existing_membership(self, tenant_id: str, account_id: str, user_id: str) -> TenantAccountUser | None:
        return self._membership(tenant_id, account_id, user_id)

    def _detail_payload(self, row: TenantAccountUser, user: User) -> dict[str, Any]:
        return {
            "tenant_account_user_id": row.id,
            "tenant_id": row.tenant_id,
            "account_id": row.account_id,
            "user_id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone": user.phone,
            "avatar_url": user.avatar_url,
            "user_scope": user.user_scope,
            "last_login_at": user.last_login_at,
            "role": row.role,
            "is_active": row.is_active,
            "joined_at": row.joined_at,
            "invited_at": row.invited_at,
            "is_deleted": row.is_deleted,
            "row_version": row.row_version,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "created_by": row.created_by,
            "updated_by": row.updated_by,
            "deleted_by": row.deleted_by,
        }

    def _count_active_admins(
        self,
        tenant_id: str,
        account_id: str,
        *,
        exclude_user_id: str | None = None,
    ) -> int:
        filters = [
            TenantAccountUser.tenant_id == tenant_id,
            TenantAccountUser.account_id == account_id,
            TenantAccountUser.role == "admin",
            TenantAccountUser.is_deleted == False,  # noqa: E712
            TenantAccountUser.is_active == True,  # noqa: E712
        ]
        if exclude_user_id is not None:
            filters.append(TenantAccountUser.user_id != exclude_user_id)
        stmt = select(TenantAccountUser).where(*filters)
        return len(list(self._db.scalars(stmt).all()))

    def list_details_by_account(
        self,
        tenant_id: str,
        account_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_account(tenant_id, account_id)
        stmt = (
            select(TenantAccountUser, User)
            .join(User, User.id == TenantAccountUser.user_id)
            .where(
                TenantAccountUser.tenant_id == tenant_id,
                TenantAccountUser.account_id == account_id,
                TenantAccountUser.is_deleted == False,  # noqa: E712
            )
            .order_by(TenantAccountUser.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        rows = self._db.execute(stmt).all()
        return [self._detail_payload(membership, user) for membership, user in rows]

    def get_detail_for_account(
        self,
        tenant_id: str,
        account_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        self._require_account(tenant_id, account_id)
        row = self._membership(tenant_id, account_id, user_id)
        if row is None:
            not_found("TENANT_ACCOUNT_USER", "Membership not found")
        user = self._get_user_any(user_id)
        if user is None or user.is_deleted:
            not_found("USER", "User not found")
        return self._detail_payload(row, user)

    def get_membership(self, tenant_id: str, account_id: str, user_id: str) -> TenantAccountUser | None:
        return self._membership(tenant_id, account_id, user_id)

    def assert_can_manage_account_users(
        self,
        tenant_id: str,
        account_id: str,
        actor_user_id: str,
    ) -> None:
        """CRM: tenant staff with owner/admin role on ``auth.tenant_user``."""
        from mtf.auth.models.tenant_user import TenantUser

        actor = self._db.scalars(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.user_id == actor_user_id,
                TenantUser.is_deleted == False,  # noqa: E712
                TenantUser.is_active == True,  # noqa: E712
            )
            .limit(1)
        ).first()
        if actor is None or actor.role not in ("owner", "admin"):
            forbidden("AUTH", "Insufficient permissions")

    def assert_portal_account_admin(
        self,
        tenant_id: str,
        account_id: str,
        actor_user_id: str,
    ) -> TenantAccountUser:
        """Portal: account membership with ``role=admin`` on ``auth.tenant_account_user``."""
        actor = self._membership(tenant_id, account_id, actor_user_id)
        if actor is None or not actor.is_active or actor.role != "admin":
            forbidden("AUTH", "Insufficient permissions")
        return actor

    def create_for_account(
        self,
        tenant_id: str,
        account_id: str,
        data: Any,
        *,
        created_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> dict[str, Any]:
        self._require_account(tenant_id, account_id)

        email_norm = str(data.email).strip().lower()
        existing = self._get_active_user_by_email(email_norm)
        now = _utc_naive_now()
        password = getattr(data, "password", None) or None

        if existing is not None:
            if existing.user_scope != "tenant_account":
                conflict("USER", "Email belongs to a non-account user")
            if self._existing_membership(tenant_id, account_id, existing.id) is not None:
                conflict("TENANT_ACCOUNT_USER", "User is already a member of this account")
            user = existing
            before_user = row_snapshot(user)
            if data.first_name is not None:
                user.first_name = data.first_name
            if data.last_name is not None:
                user.last_name = data.last_name
            if data.phone is not None:
                user.phone = data.phone
            if data.avatar_url is not None:
                user.avatar_url = data.avatar_url
            if password:
                user.password_hash = hash_password(password)
                user.password_changed_at = now
            user.updated_by = created_by
            user.updated_at = now
            self._db.add(user)
            audit_update(
                self._db,
                entity=user,
                schema_name="auth",
                table_name="app_user",
                before=before_user,
                actor=actor,
                source=source,
                tenant_id=tenant_id,
                account_id=account_id,
            )
        else:
            if not password:
                bad_request("USER", "Password is required for new users")
            user = User(
                id=generate_id(),
                email=email_norm,
                first_name=data.first_name,
                last_name=data.last_name,
                phone=data.phone,
                avatar_url=data.avatar_url,
                password_hash=hash_password(password),
                auth_provider="local",
                user_scope="tenant_account",
                created_by=created_by,
                updated_by=created_by,
            )
            self._db.add(user)
            self._db.flush()
            audit_insert(
                self._db,
                entity=user,
                schema_name="auth",
                table_name="app_user",
                actor=actor,
                source=source,
                tenant_id=tenant_id,
                account_id=account_id,
            )

        row = TenantAccountUser(
            id=generate_id(),
            tenant_id=tenant_id,
            account_id=account_id,
            user_id=user.id,
            role=data.role,
            joined_at=now,
            created_by=created_by,
            updated_by=created_by,
        )
        self._db.add(row)
        audit_insert(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="tenant_account_user",
            actor=actor,
            source=source,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        try:
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            if is_unique_constraint_violation(exc):
                conflict("TENANT_ACCOUNT_USER", "User is already a member of this account")
            raise
        self._db.refresh(user)
        self._db.refresh(row)
        return self._detail_payload(row, user)

    def update_for_account(
        self,
        tenant_id: str,
        account_id: str,
        user_id: str,
        data: Any,
        *,
        updated_by: str | None = None,
        actor_membership: TenantAccountUser | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> dict[str, Any]:
        row = self._membership(tenant_id, account_id, user_id)
        if row is None:
            not_found("TENANT_ACCOUNT_USER", "Membership not found")

        if row.row_version != data.row_version:
            row_version_conflict("TENANT_ACCOUNT_USER")

        user = self._get_user_any(user_id)
        if user is None:
            not_found("USER", "User not found")

        if actor_membership is not None and actor_membership.user_id == user_id:
            if actor_membership.role != "admin":
                if data.role is not None or data.is_active is not None:
                    conflict("TENANT_ACCOUNT_USER", "Cannot change your own role or status")

        now = _utc_naive_now()
        before_row = row_snapshot(row)
        before_user = row_snapshot(user)

        if data.role is not None and data.role != row.role:
            if row.role == "admin" and self._count_active_admins(
                tenant_id, account_id, exclude_user_id=user_id
            ) == 0:
                conflict("TENANT_ACCOUNT_USER", "Cannot remove the last admin from the account")
            row.role = data.role

        if data.is_active is not None:
            if not data.is_active and row.role == "admin":
                if self._count_active_admins(tenant_id, account_id, exclude_user_id=user_id) == 0:
                    conflict("TENANT_ACCOUNT_USER", "Cannot deactivate the last admin")
            row.is_active = data.is_active

        if data.first_name is not None:
            user.first_name = data.first_name
        if data.last_name is not None:
            user.last_name = data.last_name
        if data.phone is not None:
            user.phone = data.phone
        if data.avatar_url is not None:
            user.avatar_url = data.avatar_url
        if getattr(data, "password", None):
            user.password_hash = hash_password(data.password)
            user.password_changed_at = now

        row.updated_at = now
        if updated_by is not None:
            row.updated_by = updated_by
            user.updated_by = updated_by
        user.updated_at = now

        self._db.add(row)
        self._db.add(user)
        audit_update(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="tenant_account_user",
            before=before_row,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        audit_update(
            self._db,
            entity=user,
            schema_name="auth",
            table_name="app_user",
            before=before_user,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        self._db.commit()
        self._db.refresh(row)
        self._db.refresh(user)
        return self._detail_payload(row, user)

    def soft_delete_for_account(
        self,
        tenant_id: str,
        account_id: str,
        user_id: str,
        *,
        deleted_by: str | None = None,
        row_version: bytes | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> TenantAccountUser:
        row = self._membership(tenant_id, account_id, user_id)
        if row is None:
            not_found("TENANT_ACCOUNT_USER", "Membership not found")

        if row_version is not None and row.row_version != row_version:
            row_version_conflict("TENANT_ACCOUNT_USER")

        if row.role == "admin" and self._count_active_admins(
            tenant_id, account_id, exclude_user_id=user_id
        ) == 0:
            conflict("TENANT_ACCOUNT_USER", "Cannot remove the last admin from the account")

        before = row_snapshot(row)
        row.is_active = False
        row.is_deleted = True
        row.deleted_by = deleted_by
        row.updated_at = _utc_naive_now()
        if deleted_by is not None:
            row.updated_by = deleted_by

        self._db.add(row)
        audit_soft_delete(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="tenant_account_user",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        self._db.commit()
        self._db.refresh(row)
        return row
