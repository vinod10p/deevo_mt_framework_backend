"""Tenant account application service — `tenant.tenant_account` CRUD."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from mtf.shared.exceptions import conflict, not_found, row_version_conflict
from mtf.shared.security import generate_id
from mtf.tenant.models import Tenant, TenantAccount
from mtf.tenant.schemas.tenant_account import TenantAccountCreate, TenantAccountUpdate


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _like_pattern(raw: str) -> tuple[str, str]:
    esc = raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%", "\\"


class TenantAccountService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def _require_tenant_row(self, tenant_id: str) -> Tenant:
        tenant = self._db.scalars(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.is_deleted == False,  # noqa: E712
            )
        ).first()
        if tenant is None:
            not_found("TENANT_TENANT", "Tenant not found")
        return tenant

    def _row_by_code(self, tenant_id: str, account_code: str) -> TenantAccount | None:
        code = account_code.strip()
        stmt = select(TenantAccount).where(
            TenantAccount.tenant_id == tenant_id,
            TenantAccount.account_code == code,
            TenantAccount.is_deleted == False,  # noqa: E712
        )
        return self._db.scalars(stmt).first()

    def _list_filters(
        self,
        tenant_id: str,
        *,
        status: str | None,
        account_type: str | None,
        search: str | None,
    ) -> list:
        conditions = [
            TenantAccount.tenant_id == tenant_id,
            TenantAccount.is_deleted == False,  # noqa: E712
        ]
        if status is not None and status.strip() != "":
            conditions.append(TenantAccount.status == status.strip())
        if account_type is not None and account_type.strip() != "":
            conditions.append(TenantAccount.account_type == account_type.strip())
        if search is not None and search.strip() != "":
            pattern, esc = _like_pattern(search.strip())
            conditions.append(
                or_(
                    TenantAccount.name.like(pattern, escape=esc),
                    func.coalesce(TenantAccount.email, "").like(pattern, escape=esc),
                    TenantAccount.account_code.like(pattern, escape=esc),
                )
            )
        return conditions

    def list_accounts(
        self,
        tenant_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
        account_type: str | None = None,
        search: str | None = None,
    ) -> dict[str, object]:
        self._require_tenant_row(tenant_id)
        filters = self._list_filters(
            tenant_id,
            status=status,
            account_type=account_type,
            search=search,
        )

        count_stmt = select(func.count()).select_from(TenantAccount).where(*filters)
        total = int(self._db.scalar(count_stmt) or 0)

        list_stmt = (
            select(TenantAccount)
            .where(*filters)
            .order_by(TenantAccount.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        items = list(self._db.scalars(list_stmt).all())
        return {"items": items, "total": total, "skip": skip, "limit": limit}

    def get(self, tenant_id: str, account_id: str) -> TenantAccount | None:
        stmt = select(TenantAccount).where(
            TenantAccount.id == account_id,
            TenantAccount.tenant_id == tenant_id,
            TenantAccount.is_deleted == False,  # noqa: E712
        )
        return self._db.scalars(stmt).first()

    def require_account(self, tenant_id: str, account_id: str) -> TenantAccount:
        row = self.get(tenant_id, account_id)
        if row is None:
            not_found("TENANT_ACCOUNT", "Account not found")
        return row

    def get_by_id(self, account_id: str, tenant_id: str) -> TenantAccount:
        return self.require_account(tenant_id, account_id)

    def create(
        self,
        data: TenantAccountCreate,
        tenant_id: str,
        *,
        created_by: str | None = None,
    ) -> TenantAccount:
        self._require_tenant_row(tenant_id)

        code = data.account_code.strip()
        if self._row_by_code(tenant_id, code) is not None:
            conflict("TENANT_ACCOUNT", "Account code already exists")

        payload = data.model_dump(exclude_none=True)
        payload["account_code"] = code

        row = TenantAccount(
            id=generate_id(),
            tenant_id=tenant_id,
            created_by=created_by,
            updated_by=created_by,
            **payload,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def update(
        self,
        account_id: str,
        tenant_id: str,
        data: TenantAccountUpdate,
        *,
        updated_by: str | None = None,
    ) -> TenantAccount:
        row = self.require_account(tenant_id, account_id)

        if row.row_version != data.row_version:
            row_version_conflict("TENANT_ACCOUNT")

        updates = data.model_dump(exclude_none=True, exclude={"row_version"})
        if "account_code" in updates:
            new_code = updates["account_code"].strip()
            updates["account_code"] = new_code
            existing = self._row_by_code(tenant_id, new_code)
            if existing is not None and existing.id != row.id:
                conflict("TENANT_ACCOUNT", "Account code already exists")

        for key, value in updates.items():
            setattr(row, key, value)

        row.updated_at = _utc_naive_now()
        if updated_by is not None:
            row.updated_by = updated_by

        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def soft_delete(
        self,
        account_id: str,
        tenant_id: str,
        *,
        deleted_by: str | None = None,
        row_version: bytes | None = None,
    ) -> TenantAccount:
        row = self.require_account(tenant_id, account_id)

        if row_version is not None and row.row_version != row_version:
            row_version_conflict("TENANT_ACCOUNT")

        row.is_deleted = True
        row.deleted_by = deleted_by
        row.updated_at = _utc_naive_now()
        if deleted_by is not None:
            row.updated_by = deleted_by

        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row
