"""Tenant application service — `tenant.tenant` CRUD."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mtf.audit.service import (
    AuditSource,
    audit_insert,
    audit_soft_delete,
    audit_update,
    row_snapshot,
)
from mtf.auth.services.membership_rbac import copy_default_role_reports
from mtf.shared.clock import utc_now
from mtf.shared.db_integrity import is_unique_constraint_violation
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import conflict, not_found, row_version_conflict
from mtf.tenant.business_units import create_default_units
from mtf.tenant.models import Tenant
from mtf.tenant.schemas import TenantCreate, TenantUpdate
from mtf.tenant.services.rbac_screens import enable_screen_rbac


class TenantService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_tenants(self, *, skip: int = 0, limit: int = 100) -> list[Tenant]:
        stmt = (
            select(Tenant)
            .where(Tenant.is_deleted == False)  # noqa: E712
            .order_by(Tenant.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        stmt = select(Tenant).where(
            Tenant.id == tenant_id,
            Tenant.is_deleted == False,  # noqa: E712
        )
        return self._db.scalars(stmt).first()

    def get_by_subdomain(self, subdomain: str) -> Tenant | None:
        """Return the tenant matching the subdomain slug, or None if not found.

        Case-insensitive match. Only non-deleted tenants.
        """
        slug = subdomain.strip().lower()
        stmt = (
            select(Tenant)
            .where(
                func.lower(Tenant.subdomain) == slug,
                Tenant.is_deleted == False,  # noqa: E712
            )
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def require_tenant(self, tenant_id: str) -> Tenant:
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            not_found("TENANT_TENANT", "Tenant not found")
        return tenant

    def create_tenant(
        self,
        data: TenantCreate,
        *,
        created_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Tenant:
        """Create a tenant with its root unit, first store, default report grants and flags."""
        tenant = Tenant.new(by=created_by, **data.model_dump(exclude_none=True))
        self._db.add(tenant)
        try:
            self._db.flush()
            create_default_units(self._db, tenant, created_by=created_by)
            audit_insert(
                self._db,
                entity=tenant,
                schema_name="tenant",
                table_name="tenant",
                actor=actor,
                source=source,
                tenant_id=tenant.id,
            )
            copy_default_role_reports(
                self._db,
                tenant_id=tenant.id,
                created_by=created_by,
                actor=actor,
                source=source,
            )
            enable_screen_rbac(
                self._db,
                tenant_id=tenant.id,
                created_by=created_by,
            )
            self._db.commit()
        except IntegrityError as e:
            self._db.rollback()
            if is_unique_constraint_violation(e):
                conflict(
                    "TENANT_SUBDOMAIN",
                    "A tenant with this subdomain already exists.",
                )
            raise
        self._db.refresh(tenant)
        return tenant

    def update_tenant(
        self,
        tenant_id: str,
        data: TenantUpdate,
        *,
        updated_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Tenant:
        tenant = self.require_tenant(tenant_id)

        if tenant.row_version != data.row_version:
            row_version_conflict("TENANT_TENANT")

        before = row_snapshot(tenant)
        updates = data.model_dump(exclude_none=True, exclude={"row_version"})
        for key, value in updates.items():
            setattr(tenant, key, value)

        tenant.updated_at = utc_now()
        if updated_by is not None:
            tenant.updated_by = updated_by

        self._db.add(tenant)
        audit_update(
            self._db,
            entity=tenant,
            schema_name="tenant",
            table_name="tenant",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant.id,
        )
        try:
            self._db.commit()
        except IntegrityError as e:
            self._db.rollback()
            if is_unique_constraint_violation(e):
                conflict(
                    "TENANT_SUBDOMAIN",
                    "A tenant with this subdomain already exists.",
                )
            raise
        self._db.refresh(tenant)
        return tenant

    def soft_delete_tenant(
        self,
        tenant_id: str,
        *,
        deleted_by: str,
        row_version: bytes | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Tenant:
        tenant = self.require_tenant(tenant_id)

        if row_version is not None and tenant.row_version != row_version:
            row_version_conflict("TENANT_TENANT")

        before = row_snapshot(tenant)
        tenant.mark_deleted(deleted_by)
        audit_soft_delete(
            self._db,
            entity=tenant,
            schema_name="tenant",
            table_name="tenant",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant.id,
        )
        self._db.commit()
        self._db.refresh(tenant)
        return tenant
