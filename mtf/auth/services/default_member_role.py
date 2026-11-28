"""Per-user switch for the automatic ``tenant_member`` assignment.

``auth.tenant_user.default_member_role_enabled`` is written only here. The flag
and the matching ``auth.user_role`` change commit together, under the same
membership row lock that staff profile updates take.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.service import AuditSource, audit_update, row_snapshot
from mtf.auth.models.role import Role
from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user import User
from mtf.auth.models.user_role import UserRole
from mtf.auth.schemas.default_member_role import DefaultMemberRoleRead, DefaultMemberRoleUpdate
from mtf.auth.services.membership_rbac import (
    DEFAULT_MEMBER_ROLE_CODE,
    default_member_role_applies,
    lock_membership,
    require_platform_role,
    sync_tenant_user_role,
)
from mtf.auth.services.permission_resolver import PermissionResolver
from mtf.auth.services.rbac_assignment import (
    assert_no_escalation,
    assert_not_last_admin,
    permission_codes_for_role,
)
from mtf.shared.clock import utc_now
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import conflict, not_found, row_version_conflict


def is_default_member_template(role: Role) -> bool:
    return (
        role.tenant_id is None
        and role.user_scope == "tenant"
        and role.code == DEFAULT_MEMBER_ROLE_CODE
    )


class DefaultMemberRoleService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def _require_target(self, tenant_id: str, user_id: str, *, lock: bool) -> TenantUser:
        """Active staff membership in this tenant, else the same 404 for every miss."""
        stmt = (
            select(TenantUser)
            .join(User, User.id == TenantUser.user_id)
            .where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.user_id == user_id,
                TenantUser.is_active == True,  # noqa: E712
                TenantUser.is_deleted == False,  # noqa: E712
                User.user_scope == "tenant",
                User.is_deleted == False,  # noqa: E712
            )
        )
        if lock:
            stmt = lock_membership(stmt)
        row = self._db.scalars(stmt).first()
        if row is None:
            not_found("TENANT_USER", "Membership not found")
        return row

    def _live_template(self, tenant_id: str, user_id: str, role_id: str) -> UserRole | None:
        return self._db.scalars(
            select(UserRole).where(
                UserRole.tenant_id == tenant_id,
                UserRole.user_id == user_id,
                UserRole.account_id.is_(None),
                UserRole.role_id == role_id,
                UserRole.is_deleted == False,  # noqa: E712
            )
        ).first()

    @staticmethod
    def _read(row: TenantUser) -> DefaultMemberRoleRead:
        return DefaultMemberRoleRead(
            default_member_role_enabled=bool(row.default_member_role_enabled),
            applicable=default_member_role_applies(row.role),
            row_version=row.row_version,
        )

    def get(self, tenant_id: str, user_id: str) -> DefaultMemberRoleRead:
        return self._read(self._require_target(tenant_id, user_id, lock=False))

    def update(
        self,
        tenant_id: str,
        user_id: str,
        data: DefaultMemberRoleUpdate,
        *,
        resolver: PermissionResolver,
        actor: CurrentUser,
        source: AuditSource | None = None,
    ) -> DefaultMemberRoleRead:
        row = self._require_target(tenant_id, user_id, lock=True)
        if row.row_version != data.row_version:
            row_version_conflict("TENANT_USER")
        if not default_member_role_applies(row.role):
            conflict(
                "TENANT_USER",
                "Only Members and Viewers can change the default Member role; "
                "Owners and Admins always get tenant_admin",
            )

        enabled = data.default_member_role_enabled
        template = require_platform_role(
            self._db, code=DEFAULT_MEMBER_ROLE_CODE, user_scope="tenant"
        )
        live = self._live_template(tenant_id, user_id, template.id)
        if bool(row.default_member_role_enabled) == enabled and (live is not None) == enabled:
            return self._read(row)

        if enabled:
            assert_no_escalation(
                resolver,
                actor,
                permission_codes_for_role(self._db, template.id),
                db=self._db,
            )
        elif live is not None:
            assert_not_last_admin(
                self._db, tenant_id, drop_user_id=user_id, drop_role_id=template.id
            )

        before = row_snapshot(row)
        row.default_member_role_enabled = enabled
        row.updated_at = utc_now()
        row.updated_by = actor.user_id
        self._db.add(row)
        audit_update(
            self._db,
            entity=row,
            schema_name="auth",
            table_name="tenant_user",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        sync_tenant_user_role(
            self._db,
            tenant_id=tenant_id,
            user_id=user_id,
            membership_role=row.role,
            is_active=True,
            default_member_role_enabled=enabled,
            actor_id=actor.user_id,
            actor=actor,
            source=source,
        )
        self._db.commit()
        self._db.refresh(row)
        return self._read(row)
