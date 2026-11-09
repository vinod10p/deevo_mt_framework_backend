"""Tenant membership service — `auth.tenant_user`."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
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
from mtf.auth.models import TenantUser, User
from mtf.auth.schemas.tenant_user import TenantMembershipCreate, TenantMembershipUpdate
from mtf.auth.services.membership_rbac import (
    revoke_tenant_user_roles,
    sync_tenant_user_role,
)
from mtf.shared.db_integrity import is_unique_constraint_violation
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import bad_request, conflict, forbidden, not_found, row_version_conflict
from mtf.shared.security import generate_id, hash_password
from mtf.tenant.models import Tenant


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TenantUserService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def _require_tenant(self, tenant_id: str) -> Tenant:
        tenant = self._db.scalars(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.is_deleted == False,  # noqa: E712
            )
        ).first()
        if tenant is None:
            not_found("TENANT", "Tenant not found")
        return tenant

    def _get_user_any(self, user_id: str) -> User | None:
        stmt = select(User).where(User.id == user_id).limit(1)
        return self._db.scalars(stmt).first()

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

    def _membership_by_tenant_and_user(
        self,
        tenant_id: str,
        user_id: str,
        *,
        include_deleted: bool = False,
    ) -> TenantUser | None:
        filters = [
            TenantUser.tenant_id == tenant_id,
            TenantUser.user_id == user_id,
        ]
        if not include_deleted:
            filters.append(TenantUser.is_deleted == False)  # noqa: E712
        stmt = select(TenantUser).where(*filters).limit(1)
        return self._db.scalars(stmt).first()

    def _raise_email_in_use(self) -> None:
        raise HTTPException(
            status_code=409,
            detail={"code": "EMAIL_IN_USE", "message": "Email already registered"},
        )

    def _detail_payload(self, row: TenantUser, user: User) -> dict[str, Any]:
        return {
            "tenant_user_id": row.id,
            "tenant_id": row.tenant_id,
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

    def list_by_tenant(self, tenant_id: str, *, skip: int = 0, limit: int = 100) -> list[TenantUser]:
        stmt = (
            select(TenantUser)
            .where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.is_deleted == False,  # noqa: E712
            )
            .order_by(TenantUser.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def list_by_user(self, user_id: str, *, skip: int = 0, limit: int = 100) -> list[TenantUser]:
        stmt = (
            select(TenantUser)
            .where(
                TenantUser.user_id == user_id,
                TenantUser.is_deleted == False,  # noqa: E712
            )
            .order_by(TenantUser.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def get(self, tenant_user_id: str) -> TenantUser | None:
        stmt = select(TenantUser).where(
            TenantUser.id == tenant_user_id,
            TenantUser.is_deleted == False,  # noqa: E712
        )
        return self._db.scalars(stmt).first()

    def _existing_membership(self, tenant_id: str, user_id: str) -> TenantUser | None:
        stmt = select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.user_id == user_id,
            TenantUser.is_deleted == False,  # noqa: E712
        )
        return self._db.scalars(stmt).first()

    def list_details_by_tenant(
        self,
        tenant_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_tenant(tenant_id)
        stmt = (
            select(TenantUser, User)
            .join(User, User.id == TenantUser.user_id)
            .where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.is_deleted == False,  # noqa: E712
            )
            .order_by(TenantUser.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        rows = self._db.execute(stmt).all()
        return [self._detail_payload(membership, user) for membership, user in rows]

    def get_detail_for_tenant(self, tenant_id: str, user_id: str) -> dict[str, Any]:
        self._require_tenant(tenant_id)
        row = self._membership_by_tenant_and_user(tenant_id, user_id)
        if row is None:
            not_found("TENANT_USER", "Membership not found")
        user = self._get_user_any(user_id)
        if user is None or user.is_deleted:
            not_found("USER", "User not found")
        return self._detail_payload(row, user)

    def get_membership(self, tenant_id: str, user_id: str) -> TenantUser | None:
        return self._membership_by_tenant_and_user(tenant_id, user_id)

    def assert_can_manage_users(self, tenant_id: str, actor_user_id: str) -> TenantUser:
        actor = self._membership_by_tenant_and_user(tenant_id, actor_user_id)
        if actor is None or not actor.is_active:
            not_found("TENANT_USER", "Membership not found")
        if actor.role not in ("owner", "admin"):
            forbidden("AUTH", "Insufficient permissions")
        return actor

    def _count_active_owners(self, tenant_id: str, *, exclude_user_id: str | None = None) -> int:
        filters = [
            TenantUser.tenant_id == tenant_id,
            TenantUser.role == "owner",
            TenantUser.is_deleted == False,  # noqa: E712
            TenantUser.is_active == True,  # noqa: E712
        ]
        if exclude_user_id is not None:
            filters.append(TenantUser.user_id != exclude_user_id)
        stmt = select(TenantUser).where(*filters)
        return len(list(self._db.scalars(stmt).all()))

    def create_for_tenant(
        self,
        tenant_id: str,
        data: Any,
        *,
        created_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> dict[str, Any]:
        self._require_tenant(tenant_id)

        email_norm = str(data.email).strip().lower()
        existing = self._get_active_user_by_email(email_norm)
        now = _utc_naive_now()

        password = getattr(data, "password", None) or None

        if existing is not None:
            if existing.user_scope != "tenant":
                conflict("USER", "Email belongs to a non-tenant account")
            if self._existing_membership(tenant_id, existing.id) is not None:
                self._raise_email_in_use()
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
                user_scope="tenant",
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
            )

        row = TenantUser(
            id=generate_id(),
            tenant_id=tenant_id,
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
            table_name="tenant_user",
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        sync_tenant_user_role(
            self._db,
            tenant_id=tenant_id,
            user_id=user.id,
            membership_role=row.role,
            is_active=row.is_active is not False,
            actor_id=created_by,
            actor=actor,
            source=source,
        )
        try:
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            if is_unique_constraint_violation(exc):
                conflict("TENANT_USER", "User is already a member of this tenant")
            raise
        self._db.refresh(user)
        self._db.refresh(row)
        return self._detail_payload(row, user)

    def update_for_tenant(
        self,
        tenant_id: str,
        user_id: str,
        data: Any,
        *,
        updated_by: str | None = None,
        actor_membership: TenantUser | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> dict[str, Any]:
        row = self._membership_by_tenant_and_user(tenant_id, user_id)
        if row is None:
            not_found("TENANT_USER", "Membership not found")

        if row.row_version != data.row_version:
            row_version_conflict("TENANT_USER")

        user = self._get_user_any(user_id)
        if user is None:
            not_found("USER", "User not found")

        if actor_membership is not None and actor_membership.user_id == user_id:
            if actor_membership.role not in ("owner", "admin"):
                if data.role is not None or data.is_active is not None:
                    conflict("TENANT_USER", "Cannot change your own role or status")
            elif data.role is not None and data.role == "owner":
                conflict("TENANT_USER", "Cannot assign owner role to yourself")

        now = _utc_naive_now()
        before_row = row_snapshot(row)
        before_user = row_snapshot(user)

        if data.role is not None and data.role != row.role:
            if row.role == "owner" and self._count_active_owners(tenant_id, exclude_user_id=user_id) == 0:
                conflict("TENANT_USER", "Cannot remove the last owner from the tenant")
            row.role = data.role

        if data.is_active is not None:
            if not data.is_active and row.role == "owner":
                if self._count_active_owners(tenant_id, exclude_user_id=user_id) == 0:
                    conflict("TENANT_USER", "Cannot deactivate the last owner")
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
            table_name="tenant_user",
            before=before_row,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
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
        )
        sync_tenant_user_role(
            self._db,
            tenant_id=tenant_id,
            user_id=user_id,
            membership_role=row.role,
            is_active=row.is_active is not False,
            actor_id=updated_by,
            actor=actor,
            source=source,
        )
        self._db.commit()
        self._db.refresh(row)
        self._db.refresh(user)
        return self._detail_payload(row, user)

    def soft_delete_for_tenant(
        self,
        tenant_id: str,
        user_id: str,
        *,
        deleted_by: str | None = None,
        row_version: bytes | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> TenantUser:
        row = self._membership_by_tenant_and_user(tenant_id, user_id)
        if row is None:
            not_found("TENANT_USER", "Membership not found")

        if row_version is not None and row.row_version != row_version:
            row_version_conflict("TENANT_USER")

        if row.role == "owner" and self._count_active_owners(tenant_id, exclude_user_id=user_id) == 0:
            conflict("TENANT_USER", "Cannot remove the last owner from the tenant")

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
            table_name="tenant_user",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        revoke_tenant_user_roles(
            self._db,
            tenant_id=tenant_id,
            user_id=user_id,
            actor_id=deleted_by,
            actor=actor,
            source=source,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def create(
        self,
        data: TenantMembershipCreate,
        *,
        created_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> TenantUser:
        self._require_tenant(data.tenant_id)

        user = self._db.scalars(
            select(User).where(
                User.id == data.user_id,
                User.is_deleted == False,  # noqa: E712
            )
        ).first()
        if user is None:
            not_found("USER", "User not found")
        if user.user_scope != "tenant":
            conflict("USER", "Only tenant-scoped users can be linked")

        if self._existing_membership(data.tenant_id, data.user_id) is not None:
            conflict("TENANT_USER", "User is already a member of this tenant")

        row = TenantUser(
            id=generate_id(),
            tenant_id=data.tenant_id,
            user_id=data.user_id,
            role=data.role,
            invited_at=data.invited_at,
            invited_by=data.invited_by,
            joined_at=data.joined_at,
            created_by=created_by,
            updated_by=created_by,
        )
        self._db.add(row)
        audit_insert(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="tenant_user",
            actor=actor,
            source=source,
            tenant_id=data.tenant_id,
        )
        sync_tenant_user_role(
            self._db,
            tenant_id=data.tenant_id,
            user_id=data.user_id,
            membership_role=row.role,
            is_active=row.is_active is not False,
            actor_id=created_by,
            actor=actor,
            source=source,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def update(
        self,
        tenant_user_id: str,
        data: TenantMembershipUpdate,
        *,
        updated_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> TenantUser:
        row = self.get(tenant_user_id)
        if row is None:
            not_found("TENANT_USER", "Membership not found")

        if row.row_version != data.row_version:
            row_version_conflict("TENANT_USER")

        before = row_snapshot(row)
        updates = data.model_dump(exclude_none=True, exclude={"row_version"})
        for key, value in updates.items():
            setattr(row, key, value)

        row.updated_at = _utc_naive_now()
        if updated_by is not None:
            row.updated_by = updated_by

        self._db.add(row)
        audit_update(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="tenant_user",
            before=before,
            actor=actor,
            source=source,
            tenant_id=row.tenant_id,
        )
        if row.is_deleted:
            revoke_tenant_user_roles(
                self._db,
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                actor_id=updated_by,
                actor=actor,
                source=source,
            )
        else:
            sync_tenant_user_role(
                self._db,
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                membership_role=row.role,
                is_active=row.is_active is not False,
                actor_id=updated_by,
                actor=actor,
                source=source,
            )
        self._db.commit()
        self._db.refresh(row)
        return row

    def soft_delete(
        self,
        tenant_user_id: str,
        *,
        deleted_by: str | None = None,
        row_version: bytes | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> TenantUser:
        row = self.get(tenant_user_id)
        if row is None:
            not_found("TENANT_USER", "Membership not found")

        if row_version is not None and row.row_version != row_version:
            row_version_conflict("TENANT_USER")

        before = row_snapshot(row)
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
            table_name="tenant_user",
            before=before,
            actor=actor,
            source=source,
            tenant_id=row.tenant_id,
        )
        revoke_tenant_user_roles(
            self._db,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            actor_id=deleted_by,
            actor=actor,
            source=source,
        )
        self._db.commit()
        self._db.refresh(row)
        return row
