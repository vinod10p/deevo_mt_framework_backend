"""Tenant application service — `tenant.tenant` CRUD."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mtf.shared.db_integrity import is_unique_constraint_violation
from mtf.shared.exceptions import conflict, not_found, row_version_conflict
from mtf.shared.security import generate_id
from mtf.tenant.models import Tenant
from mtf.tenant.schemas import TenantCreate, TenantUpdate


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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

    def create_tenant(self, data: TenantCreate, *, created_by: str | None = None) -> Tenant:
        tenant = Tenant(
            id=generate_id(),
            created_by=created_by,
            updated_by=created_by,
            **data.model_dump(exclude_none=True),
        )
        self._db.add(tenant)
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

    def update_tenant(
        self,
        tenant_id: str,
        data: TenantUpdate,
        *,
        updated_by: str | None = None,
    ) -> Tenant:
        tenant = self.require_tenant(tenant_id)

        if tenant.row_version != data.row_version:
            row_version_conflict("TENANT_TENANT")

        updates = data.model_dump(exclude_none=True, exclude={"row_version"})
        for key, value in updates.items():
            setattr(tenant, key, value)

        tenant.updated_at = _utc_naive_now()
        if updated_by is not None:
            tenant.updated_by = updated_by

        self._db.add(tenant)
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
        deleted_by: str | None = None,
        row_version: bytes | None = None,
    ) -> Tenant:
        tenant = self.require_tenant(tenant_id)

        if row_version is not None and tenant.row_version != row_version:
            row_version_conflict("TENANT_TENANT")

        tenant.is_deleted = True
        tenant.deleted_by = deleted_by
        tenant.updated_at = _utc_naive_now()
        if deleted_by is not None:
            tenant.updated_by = deleted_by

        self._db.add(tenant)
        self._db.commit()
        self._db.refresh(tenant)
        return tenant
