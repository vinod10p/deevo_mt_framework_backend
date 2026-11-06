"""Audit domain services — list/get plus append-only writes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Optional

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.models import AuditLog
from mtf.audit.schemas import DATA_CHANGE_ACTIONS, AuditAction, AuditLogCreate
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import forbidden
from mtf.shared.security import generate_id

_UNSET = object()

#: Keys dropped from old_values / new_values (case-insensitive).
SECRET_VALUE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "token_hash",
        "refresh_token_hash",
        "invite_token_hash",
        "access_token",
        "refresh_token",
        "client_secret",
        "api_key",
        "id_token",
        "oauth_token",
        "oauth_refresh_token",
        "mfa_secret_enc",
        "row_version",
    }
)


@dataclass(frozen=True)
class AuditSource:
    """Request origin recorded on ``audit.audit_log`` rows."""

    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    session_id: str | None = None


def row_snapshot(instance: object) -> dict[str, Any]:
    """Column map for ``old_values`` / ``new_values``. Secrets are stripped on write."""
    mapper = sa_inspect(instance).mapper
    return {attr.key: getattr(instance, attr.key) for attr in mapper.column_attrs}


def changed_audit_values(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Same keys in old and new — fields that actually changed."""
    keys = [key for key in after if before.get(key) != after.get(key)]
    return {key: before.get(key) for key in keys}, {key: after[key] for key in keys}


def sanitize_audit_values(value: Any) -> Any:
    """Drop secrets and make a JSON-object-safe structure (dicts/lists/scalars)."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name.lower() in SECRET_VALUE_KEYS:
                continue
            out[name] = sanitize_audit_values(item)
        return out
    if isinstance(value, (list, tuple)):
        return [sanitize_audit_values(item) for item in value]
    if isinstance(value, bytes):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _json_object(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("Audit old_values/new_values must be a JSON object")
    return json.dumps(sanitize_audit_values(value), ensure_ascii=False)


def _require_data_change_shape(
    action: str,
    schema_name: str | None,
    table_name: str | None,
    record_id: str | None,
    old_values: Mapping[str, Any] | None,
    new_values: Mapping[str, Any] | None,
) -> None:
    if action not in DATA_CHANGE_ACTIONS:
        return
    if not schema_name or not table_name or not record_id:
        raise ValueError(
            "Data-change audit rows require schema_name, table_name, and record_id"
        )
    if action == "insert":
        if old_values is not None or new_values is None:
            raise ValueError("insert audit rows require new_values and null old_values")
        return
    if action in ("update", "restore"):
        if old_values is None or new_values is None:
            raise ValueError(f"{action} audit rows require both old_values and new_values")
        return
    if old_values is None:
        raise ValueError("delete audit rows require old_values")


def append_audit_log(
    db: Session,
    *,
    action: AuditAction,
    actor: CurrentUser | None = None,
    source: AuditSource | None = None,
    schema_name: str | None = None,
    table_name: str | None = None,
    record_id: str | None = None,
    old_values: Mapping[str, Any] | None = None,
    new_values: Mapping[str, Any] | None = None,
    reason: str | None = None,
    tenant_id: Any = _UNSET,
    account_id: Any = _UNSET,
    session_id: Any = _UNSET,
    user_id: Any = _UNSET,
    user_type: Any = _UNSET,
    request_id: Any = _UNSET,
) -> AuditLog:
    """Add an ``audit.audit_log`` row. Does not commit — caller owns the transaction."""
    source = source or AuditSource()
    _require_data_change_shape(
        action, schema_name, table_name, record_id, old_values, new_values
    )

    if tenant_id is _UNSET:
        tenant_id = actor.tenant_id if actor is not None else None
    if account_id is _UNSET:
        account_id = actor.account_id if actor is not None else None
    if user_id is _UNSET:
        user_id = actor.user_id if actor is not None else None
    if user_type is _UNSET:
        user_type = actor.user_scope if actor is not None else None
    if session_id is _UNSET:
        session_id = source.session_id
    if request_id is _UNSET:
        request_id = source.request_id

    log = AuditLog(
        id=generate_id(),
        tenant_id=tenant_id,
        account_id=account_id,
        session_id=session_id,
        request_id=request_id,
        user_id=user_id,
        user_type=user_type,
        schema_name=schema_name,
        table_name=table_name,
        record_id=record_id,
        action=action,
        old_values=_json_object(old_values),
        new_values=_json_object(new_values),
        ip_address=source.ip_address,
        user_agent=source.user_agent,
        reason=reason,
    )
    db.add(log)
    return log


def _identity_kwargs(*, tenant_id: Any, account_id: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if tenant_id is not _UNSET:
        values["tenant_id"] = tenant_id
    if account_id is not _UNSET:
        values["account_id"] = account_id
    return values


def audit_insert(
    db: Session,
    *,
    entity: object,
    schema_name: str,
    table_name: str,
    actor: CurrentUser | None = None,
    source: AuditSource | None = None,
    tenant_id: Any = _UNSET,
    account_id: Any = _UNSET,
) -> AuditLog:
    return append_audit_log(
        db,
        action="insert",
        actor=actor,
        source=source,
        schema_name=schema_name,
        table_name=table_name,
        record_id=getattr(entity, "id"),
        new_values=row_snapshot(entity),
        **_identity_kwargs(tenant_id=tenant_id, account_id=account_id),
    )


def audit_update(
    db: Session,
    *,
    entity: object,
    schema_name: str,
    table_name: str,
    before: Mapping[str, Any],
    actor: CurrentUser | None = None,
    source: AuditSource | None = None,
    tenant_id: Any = _UNSET,
    account_id: Any = _UNSET,
) -> AuditLog | None:
    old_values, new_values = changed_audit_values(before, row_snapshot(entity))
    if not old_values:
        return None
    return append_audit_log(
        db,
        action="update",
        actor=actor,
        source=source,
        schema_name=schema_name,
        table_name=table_name,
        record_id=getattr(entity, "id"),
        old_values=old_values,
        new_values=new_values,
        **_identity_kwargs(tenant_id=tenant_id, account_id=account_id),
    )


def audit_soft_delete(
    db: Session,
    *,
    entity: object,
    schema_name: str,
    table_name: str,
    before: Mapping[str, Any],
    actor: CurrentUser | None = None,
    source: AuditSource | None = None,
    tenant_id: Any = _UNSET,
    account_id: Any = _UNSET,
) -> AuditLog:
    return append_audit_log(
        db,
        action="delete",
        actor=actor,
        source=source,
        schema_name=schema_name,
        table_name=table_name,
        record_id=getattr(entity, "id"),
        old_values=before,
        new_values=row_snapshot(entity),
        **_identity_kwargs(tenant_id=tenant_id, account_id=account_id),
    )


def resolve_audit_read_scope(
    user: CurrentUser,
    *,
    tenant_id: str | None = None,
    account_id: str | None = None,
) -> tuple[str | None, str | None]:
    """Return ``(tenant_id, account_id)`` filters. ``None`` means no filter on that column.

    Identity always comes from the JWT. ``tenant`` / ``tenant_account`` callers cannot
    widen scope via query params. System may use those params as optional filters.
    """
    if user.user_scope == "system":
        return tenant_id, account_id
    if user.tenant_id is None:
        forbidden("AUTH", "Tenant context required")
    if user.user_scope == "tenant_account":
        if user.account_id is None:
            forbidden("AUTH", "Account context required")
        return user.tenant_id, user.account_id
    return user.tenant_id, account_id


def audit_log_visible(user: CurrentUser, log: AuditLog) -> bool:
    """Whether ``user`` may read ``log``. Wrong-tenant rows are not visible (404, not 403)."""
    tenant_id, account_id = resolve_audit_read_scope(user)
    if tenant_id is not None and log.tenant_id != tenant_id:
        return False
    if account_id is not None and log.account_id != account_id:
        return False
    return True


class AuditLogService:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_logs(
        self,
        user: CurrentUser,
        *,
        tenant_id: Optional[str] = None,
        account_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        record_id: Optional[str] = None,
        request_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AuditLog]:
        scope_tenant, scope_account = resolve_audit_read_scope(
            user, tenant_id=tenant_id, account_id=account_id
        )
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc())

        if scope_tenant is not None:
            stmt = stmt.where(AuditLog.tenant_id == scope_tenant)
        if scope_account is not None:
            stmt = stmt.where(AuditLog.account_id == scope_account)
        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if schema_name is not None:
            stmt = stmt.where(AuditLog.schema_name == schema_name)
        if table_name is not None:
            stmt = stmt.where(AuditLog.table_name == table_name)
        if record_id is not None:
            stmt = stmt.where(AuditLog.record_id == record_id)
        if request_id is not None:
            stmt = stmt.where(AuditLog.request_id == request_id)

        stmt = stmt.offset(skip).limit(limit)
        return list(self._db.scalars(stmt).all())

    def get_log(self, user: CurrentUser, log_id: str) -> AuditLog | None:
        stmt = select(AuditLog).where(AuditLog.id == log_id)
        log = self._db.scalars(stmt).first()
        if log is None or not audit_log_visible(user, log):
            return None
        return log

    def append(
        self,
        *,
        action: AuditAction,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
        schema_name: str | None = None,
        table_name: str | None = None,
        record_id: str | None = None,
        old_values: Mapping[str, Any] | None = None,
        new_values: Mapping[str, Any] | None = None,
        reason: str | None = None,
        **identity: Any,
    ) -> AuditLog:
        return append_audit_log(
            self._db,
            action=action,
            actor=actor,
            source=source,
            schema_name=schema_name,
            table_name=table_name,
            record_id=record_id,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
            **identity,
        )

    def create_log(self, data: AuditLogCreate) -> AuditLog:
        """Map ``AuditLogCreate`` onto ``append_audit_log``. Does not commit."""
        old: Mapping[str, Any] | None
        new: Mapping[str, Any] | None
        if data.old_values is None:
            old = None
        else:
            parsed_old = json.loads(data.old_values)
            if not isinstance(parsed_old, dict):
                raise ValueError("Audit old_values must be a JSON object")
            old = parsed_old
        if data.new_values is None:
            new = None
        else:
            parsed_new = json.loads(data.new_values)
            if not isinstance(parsed_new, dict):
                raise ValueError("Audit new_values must be a JSON object")
            new = parsed_new
        return append_audit_log(
            self._db,
            action=data.action,
            schema_name=data.schema_name,
            table_name=data.table_name,
            record_id=data.record_id,
            old_values=old,
            new_values=new,
            reason=data.reason,
            tenant_id=data.tenant_id,
            account_id=data.account_id,
            session_id=data.session_id,
            user_id=data.user_id,
            user_type=data.user_type,
            request_id=data.request_id,
            source=AuditSource(
                ip_address=data.ip_address,
                user_agent=data.user_agent,
                request_id=data.request_id,
                session_id=data.session_id,
            ),
        )
