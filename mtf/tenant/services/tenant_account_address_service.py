"""Tenant account address service — `tenant.tenant_account_address` CRUD."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.service import (
    AuditSource,
    audit_insert,
    audit_soft_delete,
    audit_update,
    row_snapshot,
)
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import not_found, row_version_conflict
from mtf.shared.security import generate_id
from mtf.tenant.models import TenantAccount, TenantAccountAddress
from mtf.tenant.schemas.tenant_account_address import (
    TenantAccountAddressCreate,
    TenantAccountAddressUpdate,
)


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TenantAccountAddressService:
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

    def _clear_default_flags(
        self,
        tenant_id: str,
        account_id: str,
        *,
        keep_address_id: str | None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> None:
        stmt = select(TenantAccountAddress).where(
            TenantAccountAddress.tenant_id == tenant_id,
            TenantAccountAddress.account_id == account_id,
            TenantAccountAddress.is_deleted == False,  # noqa: E712
            TenantAccountAddress.is_default == True,  # noqa: E712
        )
        if keep_address_id is not None:
            stmt = stmt.where(TenantAccountAddress.id != keep_address_id)
        now = _utc_naive_now()
        for addr in self._db.scalars(stmt):
            before = row_snapshot(addr)
            addr.is_default = False
            addr.updated_at = now
            self._db.add(addr)
            audit_update(
                self._db,
                entity=addr,
                schema_name="tenant",
                table_name="tenant_account_address",
                before=before,
                actor=actor,
                source=source,
                tenant_id=tenant_id,
                account_id=account_id,
            )

    def list_addresses(
        self,
        tenant_id: str,
        account_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[TenantAccountAddress]:
        self._require_account(tenant_id, account_id)
        stmt = (
            select(TenantAccountAddress)
            .where(
                TenantAccountAddress.tenant_id == tenant_id,
                TenantAccountAddress.account_id == account_id,
                TenantAccountAddress.is_deleted == False,  # noqa: E712
            )
            .order_by(TenantAccountAddress.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def get(
        self,
        tenant_id: str,
        account_id: str,
        address_id: str,
    ) -> TenantAccountAddress | None:
        self._require_account(tenant_id, account_id)
        stmt = select(TenantAccountAddress).where(
            TenantAccountAddress.id == address_id,
            TenantAccountAddress.tenant_id == tenant_id,
            TenantAccountAddress.account_id == account_id,
            TenantAccountAddress.is_deleted == False,  # noqa: E712
        )
        return self._db.scalars(stmt).first()

    def require_address(
        self,
        tenant_id: str,
        account_id: str,
        address_id: str,
    ) -> TenantAccountAddress:
        row = self.get(tenant_id, account_id, address_id)
        if row is None:
            not_found("TENANT_ACCOUNT_ADDRESS", "Address not found")
        return row

    def create(
        self,
        tenant_id: str,
        account_id: str,
        data: TenantAccountAddressCreate,
        *,
        created_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> TenantAccountAddress:
        self._require_account(tenant_id, account_id)

        if data.is_default:
            self._clear_default_flags(
                tenant_id,
                account_id,
                keep_address_id=None,
                actor=actor,
                source=source,
            )

        row = TenantAccountAddress(
            id=generate_id(),
            tenant_id=tenant_id,
            account_id=account_id,
            created_by=created_by,
            updated_by=created_by,
            **data.model_dump(),
        )
        self._db.add(row)
        audit_insert(
            self._db,
            entity=row,
            schema_name="tenant",
            table_name="tenant_account_address",
            actor=actor,
            source=source,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def update(
        self,
        tenant_id: str,
        account_id: str,
        address_id: str,
        data: TenantAccountAddressUpdate,
        *,
        updated_by: str | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> TenantAccountAddress:
        row = self.require_address(tenant_id, account_id, address_id)

        if row.row_version != data.row_version:
            row_version_conflict("TENANT_ACCOUNT_ADDRESS")

        before = row_snapshot(row)
        updates = data.model_dump(exclude_none=True, exclude={"row_version"})
        if updates.get("is_default") is True:
            self._clear_default_flags(
                tenant_id,
                account_id,
                keep_address_id=address_id,
                actor=actor,
                source=source,
            )

        for key, value in updates.items():
            setattr(row, key, value)

        row.updated_at = _utc_naive_now()
        if updated_by is not None:
            row.updated_by = updated_by

        self._db.add(row)
        audit_update(
            self._db,
            entity=row,
            schema_name="tenant",
            table_name="tenant_account_address",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def soft_delete(
        self,
        tenant_id: str,
        account_id: str,
        address_id: str,
        *,
        deleted_by: str | None = None,
        row_version: bytes | None = None,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> TenantAccountAddress:
        row = self.require_address(tenant_id, account_id, address_id)

        if row_version is not None and row.row_version != row_version:
            row_version_conflict("TENANT_ACCOUNT_ADDRESS")

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
            schema_name="tenant",
            table_name="tenant_account_address",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        self._db.commit()
        self._db.refresh(row)
        return row

    def get_by_id(
        self,
        tenant_id: str,
        account_id: str,
        address_id: str,
    ) -> TenantAccountAddress:
        return self.require_address(tenant_id, account_id, address_id)
