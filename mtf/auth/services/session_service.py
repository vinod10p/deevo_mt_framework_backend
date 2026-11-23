"""Authentication session lifecycle — login, refresh rotation, logout, logout-all."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Never

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from mtf.audit.service import AuditSource, append_audit_log
from mtf.auth.models.session import AuthSession
from mtf.auth.models.tenant_account_user import TenantAccountUser
from mtf.auth.models.tenant_user import TenantUser
from mtf.auth.models.user import User
from mtf.auth.schemas.session import LoginRequest, RefreshRequest, TokenResponse
from mtf.auth.services.login_throttle import LoginThrottle, ThrottleLimits, login_throttle
from mtf.shared.config import get_settings
from mtf.shared.exceptions import unauthorized
from mtf.shared.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    generate_id,
    hash_token,
    verify_password,
)
from mtf.tenant.models import Tenant, TenantAccount

logger = logging.getLogger(__name__)

_AUTH_GENERIC = "Invalid email or password"
_TENANT_REQUIRED = "Tenant is required. Please use your tenant login link."
# JWT ``user_type`` claim (subject class); ``auth.session.user_type`` stores ``user_scope``.
_JWT_USER_TYPE_APP = "app_user"
_RATE_LIMITED = "Too many login attempts. Please try again later."
#: ``_reject_login`` reasons that count as a credential guess for throttling. Others
#: (tenant_required, no_membership, …) happen *after* a correct password.
_GUESS_REASONS = frozenset({None, "locked"})


def _utc_naive_now() -> datetime:
    """UTC instant as naive ``datetime`` for ``DATETIME2`` columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SessionService:
    """Login, refresh (rotate in place), logout, and logout-all for ``auth.session``."""

    def __init__(self, db: Session, *, throttle: LoginThrottle | None = None) -> None:
        self._db = db
        self._throttle = throttle or login_throttle

    def login(
        self,
        request: LoginRequest,
        *,
        source: AuditSource | None = None,
    ) -> TokenResponse:
        now = _utc_naive_now()
        email_norm = request.email.strip().lower()
        source = source or AuditSource()
        settings = get_settings()

        # Throttle before touching the password or writing audit rows, so a flood of
        # guesses costs neither a bcrypt check nor an audit insert.
        retry_after = self._throttle.retry_after(
            source.ip_address,
            email_norm,
            ThrottleLimits(
                max_failures_per_ip=settings.login_max_failures_per_ip,
                max_failures_per_account_ip=settings.login_max_failures_per_account_ip,
                window_seconds=settings.login_failure_window_seconds,
            ),
        )
        if retry_after is not None:
            logger.warning(
                "Login throttled for %s from %s (retry in %ss)",
                email_norm,
                source.ip_address,
                retry_after,
            )
            raise HTTPException(
                status_code=429,
                detail={"code": "AUTH_RATE_LIMITED", "message": _RATE_LIMITED},
                headers={"Retry-After": str(retry_after)},
            )

        user = self._get_active_user_by_email(email_norm)
        if user is None:
            self._reject_login(source, email_norm)

        if user.locked_until is not None and user.locked_until > now:
            self._reject_login(
                source,
                email_norm,
                user=user,
                reason="locked",
                message="Account is temporarily locked",
            )

        if not verify_password(request.password, user.password_hash or ""):
            user.failed_login_count = user.failed_login_count + 1
            # Account-wide backstop against guessing from many IPs; per-IP limits above
            # mean one attacker cannot reach it quickly.
            if user.failed_login_count >= settings.login_account_lockout_threshold:
                user.locked_until = now + timedelta(
                    minutes=settings.login_account_lockout_minutes
                )
            self._db.add(user)
            self._reject_login(source, email_norm, user=user)

        self._throttle.record_success(source.ip_address, email_norm)
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        self._db.add(user)

        tenant_id: str | None = None
        account_id: str | None = None
        account_name: str | None = None

        if user.user_scope == "system":
            pass
        elif user.user_scope == "tenant":
            if request.tenant_id is None:
                self._reject_login(
                    source, email_norm, user=user, reason="tenant_required",
                    message=_TENANT_REQUIRED,
                )
            self._require_active_tenant(request.tenant_id)
            membership = self._get_active_tenant_membership(user.id, request.tenant_id)
            if membership is None:
                self._reject_login(
                    source, email_norm, user=user, tenant_id=request.tenant_id,
                    reason="no_membership",
                )
            tenant_id = request.tenant_id
        elif user.user_scope == "tenant_account":
            if request.tenant_id is None:
                self._reject_login(
                    source, email_norm, user=user, reason="tenant_required",
                    message=_TENANT_REQUIRED,
                )
            self._require_active_tenant(request.tenant_id)
            account_id = self._require_single_account_membership(user.id, request.tenant_id)
            tenant_id = request.tenant_id
            account_name = self._account_name(account_id)
        else:
            self._reject_login(source, email_norm, user=user, reason="invalid_scope")

        session_id = generate_id()
        access_token = create_access_token(
            user.id,
            _JWT_USER_TYPE_APP,
            user.user_scope,
            tenant_id,
            account_id,
            session_id=session_id,
        )
        refresh_token = create_refresh_token(user.id, session_id)

        token_h = hash_token(access_token)
        refresh_h = hash_token(refresh_token)

        session = self._create_session(
            session_id=session_id,
            user_id=user.id,
            user_type=user.user_scope,
            tenant_id=tenant_id,
            token_hash=token_h,
            refresh_token_hash=refresh_h,
            auth_method="password",
            created_from=request.created_from,
            ip_address=source.ip_address,
            user_agent=source.user_agent,
        )
        self._db.add(session)

        append_audit_log(
            self._db,
            action="login",
            source=self._source(source, session_id=session.id),
            schema_name="auth",
            table_name="session",
            record_id=session.id,
            user_id=user.id,
            user_type=user.user_scope,
            tenant_id=tenant_id,
            account_id=account_id,
            new_values={"event": "login"},
        )

        self._db.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user.id,
            user_type=_JWT_USER_TYPE_APP,
            user_scope=user.user_scope,
            tenant_id=tenant_id,
            account_id=account_id,
            account_name=account_name,
            first_name=user.first_name,
            last_name=user.last_name,
            tenant_name=self._tenant_name(tenant_id),
        )

    def _create_session(
        self,
        session_id: str,
        user_id: str,
        user_type: str,
        tenant_id: str | None,
        token_hash: bytes,
        refresh_token_hash: bytes,
        auth_method: str,
        created_from: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AuthSession:
        settings = get_settings()
        now = _utc_naive_now()
        expires_at = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
        refresh_expires_at = now + timedelta(days=settings.jwt_refresh_token_expire_days)

        return AuthSession(
            id=session_id,
            user_id=user_id,
            user_type=user_type,
            tenant_id=tenant_id,
            token_hash=token_hash,
            refresh_token_hash=refresh_token_hash,
            auth_method=auth_method,
            created_from=created_from,
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
            last_activity=now,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    def refresh(
        self,
        request: RefreshRequest,
        *,
        source: AuditSource | None = None,
    ) -> TokenResponse:
        settings = get_settings()
        now = _utc_naive_now()
        incoming_hash = hash_token(request.refresh_token)

        session = self._get_session_by_refresh_hash(incoming_hash)
        if session is None:
            unauthorized("AUTH", "Invalid refresh token")

        if session.refresh_expires_at is None or session.refresh_expires_at < now:
            unauthorized("AUTH", "Refresh token expired")

        try:
            claims = decode_refresh_token(request.refresh_token)
        except ValueError as exc:
            msg = str(exc)
            if msg == "TOKEN_EXPIRED":
                unauthorized("AUTH", "Refresh token expired")
            unauthorized("AUTH", "Invalid refresh token")

        if claims.get("session_id") != session.id or claims.get("user_id") != session.user_id:
            unauthorized("AUTH", "Invalid refresh token")

        user = self._get_active_user_by_id(session.user_id)
        if user is None:
            unauthorized("AUTH", "Invalid refresh token")

        # Re-check what login checked: a suspended tenant or a removed staff member must
        # not be able to mint new tokens (their API calls already get 401 — see deps).
        if user.user_scope in ("tenant", "tenant_account"):
            if session.tenant_id is None or self._usable_tenant(session.tenant_id) is None:
                self._end_session(session, now, "tenant_inactive")
        if user.user_scope == "tenant":
            if self._get_active_tenant_membership(user.id, session.tenant_id) is None:
                self._end_session(session, now, "membership_inactive")

        account_id: str | None = None
        account_name: str | None = None
        if user.user_scope == "tenant_account":
            account_id = self._require_single_account_membership(
                user.id,
                session.tenant_id,
            )
            account_name = self._account_name(account_id)

        new_access = create_access_token(
            session.user_id,
            _JWT_USER_TYPE_APP,
            user.user_scope,
            session.tenant_id,
            account_id,
            session_id=session.id,
        )
        new_refresh = create_refresh_token(session.user_id, session.id)

        session.token_hash = hash_token(new_access)
        session.refresh_token_hash = hash_token(new_refresh)
        session.expires_at = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
        session.refresh_expires_at = now + timedelta(days=settings.jwt_refresh_token_expire_days)
        session.last_activity = now
        session.updated_at = now
        if source is not None:
            session.ip_address = source.ip_address
            session.user_agent = source.user_agent
        self._db.add(session)

        self._db.commit()

        return TokenResponse(
            access_token=new_access,
            refresh_token=new_refresh,
            user_id=session.user_id,
            user_type=_JWT_USER_TYPE_APP,
            user_scope=user.user_scope,
            tenant_id=session.tenant_id,
            account_id=account_id,
            account_name=account_name,
            first_name=user.first_name,
            last_name=user.last_name,
            tenant_name=self._tenant_name(session.tenant_id),
        )

    def logout(
        self,
        raw_access_token: str,
        current_user_id: str,
        *,
        source: AuditSource | None = None,
    ) -> None:
        session = self._get_session_by_access_hash(hash_token(raw_access_token))
        if session is not None:
            self._revoke_session(session, current_user_id, source)

    def logout_by_refresh(
        self,
        raw_refresh_token: str,
        expected_session_id: str,
        *,
        source: AuditSource | None = None,
    ) -> bool:
        session = self._get_session_by_refresh_hash(hash_token(raw_refresh_token))
        if session is None:
            return True
        if session.id != expected_session_id:
            return False
        self._revoke_session(session, session.user_id, source)
        return True

    def _revoke_session(
        self,
        session: AuthSession,
        current_user_id: str,
        source: AuditSource | None,
    ) -> None:
        now = _utc_naive_now()
        session.is_active = False
        session.revoked_at = now
        session.revoke_reason = "logout"
        session.revoked_by = current_user_id
        session.updated_at = now
        self._db.add(session)

        audit_user_scope = self._user_scope_for_audit(session.user_id)
        append_audit_log(
            self._db,
            action="logout",
            source=self._source(source, session_id=session.id),
            schema_name="auth",
            table_name="session",
            record_id=session.id,
            user_id=session.user_id,
            user_type=audit_user_scope,
            tenant_id=session.tenant_id,
            new_values={"event": "logout"},
        )
        self._db.commit()

    def logout_all(
        self,
        user_id: str,
        current_user_id: str,
        *,
        source: AuditSource | None = None,
    ) -> int:
        now = _utc_naive_now()
        stmt = select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.is_active == True,  # noqa: E712
            AuthSession.is_deleted == False,  # noqa: E712
        )
        sessions = list(self._db.scalars(stmt).all())
        for s in sessions:
            s.is_active = False
            s.revoked_at = now
            s.revoke_reason = "logout_all"
            s.revoked_by = current_user_id
            s.updated_at = now
            self._db.add(s)

        if sessions:
            audit_user_scope = self._user_scope_for_audit(user_id)
            append_audit_log(
                self._db,
                action="logout",
                source=self._source(source, session_id=sessions[0].id),
                schema_name="auth",
                table_name="session",
                record_id=sessions[0].id,
                user_id=user_id,
                user_type=audit_user_scope,
                tenant_id=sessions[0].tenant_id,
                new_values={"event": "logout_all", "revoked_count": len(sessions)},
            )
        self._db.commit()
        return len(sessions)

    def _get_active_user_by_email(self, email_norm: str) -> User | None:
        stmt = (
            select(User)
            .where(
                User.is_deleted == False,  # noqa: E712
                User.is_active == True,  # noqa: E712
                User.email_normalized == email_norm,
            )
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def _get_active_user_by_id(self, user_id: str) -> User | None:
        stmt = (
            select(User)
            .where(
                User.id == user_id,
                User.is_deleted == False,  # noqa: E712
                User.is_active == True,  # noqa: E712
            )
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def _first_active_tenant_id(self, user_id: str) -> str | None:
        stmt = (
            select(TenantUser.tenant_id)
            .where(
                TenantUser.user_id == user_id,
                TenantUser.is_deleted == False,  # noqa: E712
                TenantUser.is_active == True,  # noqa: E712
            )
            .order_by(TenantUser.created_at.asc())
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def _tenant_name(self, tenant_id: str | None) -> str | None:
        if tenant_id is None:
            return None
        stmt = (
            select(Tenant.name)
            .where(
                Tenant.id == tenant_id,
                Tenant.is_deleted == False,  # noqa: E712
            )
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def _get_active_tenant_membership(self, user_id: str, tenant_id: str) -> TenantUser | None:
        """Active ``TenantUser`` row for this user and tenant, or None."""
        stmt = (
            select(TenantUser)
            .where(
                TenantUser.user_id == user_id,
                TenantUser.tenant_id == tenant_id,
                TenantUser.is_active == True,  # noqa: E712
                TenantUser.is_deleted == False,  # noqa: E712
            )
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def _usable_tenant(self, tenant_id: str) -> Tenant | None:
        """The tenant if it exists, is active and not suspended / cancelled / expired."""
        tenant = self._db.scalars(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.is_deleted == False,  # noqa: E712
            )
            .limit(1)
        ).first()
        if tenant is None or not tenant.is_active or tenant.status in (
            "suspended",
            "cancelled",
            "expired",
        ):
            return None
        return tenant

    def _require_active_tenant(self, tenant_id: str) -> Tenant:
        tenant = self._usable_tenant(tenant_id)
        if tenant is None:
            unauthorized("AUTH", _AUTH_GENERIC)
        return tenant

    def _end_session(self, session: AuthSession, now: datetime, reason: str) -> Never:
        """Deactivate ``session`` (its access token dies too) and reject the refresh."""
        session.is_active = False
        session.revoked_at = now
        session.revoke_reason = reason
        session.updated_at = now
        self._db.add(session)
        self._db.commit()
        unauthorized("AUTH", "Invalid refresh token")

    def _list_active_account_memberships(
        self,
        user_id: str,
        tenant_id: str,
    ) -> list[TenantAccountUser]:
        stmt = (
            select(TenantAccountUser)
            .join(
                TenantAccount,
                TenantAccount.id == TenantAccountUser.account_id,
            )
            .where(
                TenantAccountUser.user_id == user_id,
                TenantAccountUser.tenant_id == tenant_id,
                TenantAccountUser.is_active == True,  # noqa: E712
                TenantAccountUser.is_deleted == False,  # noqa: E712
                TenantAccount.is_active == True,  # noqa: E712
                TenantAccount.is_deleted == False,  # noqa: E712
            )
            .order_by(TenantAccountUser.created_at.asc())
        )
        return list(self._db.scalars(stmt).all())

    def _require_single_account_membership(self, user_id: str, tenant_id: str) -> str:
        memberships = self._list_active_account_memberships(user_id, tenant_id)
        if len(memberships) == 0:
            unauthorized("AUTH", _AUTH_GENERIC)
        if len(memberships) > 1:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "MULTIPLE_ACCOUNT_MEMBERSHIPS",
                    "message": (
                        "This user belongs to more than one account under this tenant. "
                        "Contact your administrator."
                    ),
                },
            )
        return memberships[0].account_id

    def _account_name(self, account_id: str) -> str | None:
        stmt = (
            select(TenantAccount.name)
            .where(
                TenantAccount.id == account_id,
                TenantAccount.is_deleted == False,  # noqa: E712
            )
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def _get_session_by_refresh_hash(self, refresh_hash: bytes) -> AuthSession | None:
        stmt = (
            select(AuthSession)
            .where(
                AuthSession.refresh_token_hash == refresh_hash,
                AuthSession.is_active == True,  # noqa: E712
                AuthSession.is_deleted == False,  # noqa: E712
            )
            .with_hint(AuthSession, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
            .with_for_update()
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def _get_session_by_access_hash(self, token_hash: bytes) -> AuthSession | None:
        stmt = (
            select(AuthSession)
            .where(
                AuthSession.token_hash == token_hash,
                AuthSession.is_active == True,  # noqa: E712
                AuthSession.is_deleted == False,  # noqa: E712
            )
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def _user_scope_for_audit(self, user_id: str) -> str | None:
        """``audit.audit_log.user_type`` stores ``auth.app_user.user_scope``."""
        stmt = select(User.user_scope).where(User.id == user_id).limit(1)
        return self._db.scalars(stmt).first()

    @staticmethod
    def _source(source: AuditSource | None, *, session_id: str | None = None) -> AuditSource:
        source = source or AuditSource()
        if session_id is None:
            return source
        return AuditSource(
            ip_address=source.ip_address,
            user_agent=source.user_agent,
            request_id=source.request_id,
            session_id=session_id,
        )

    def _reject_login(
        self,
        source: AuditSource,
        email: str,
        *,
        user: User | None = None,
        tenant_id: str | None = None,
        account_id: str | None = None,
        reason: str | None = None,
        message: str = _AUTH_GENERIC,
    ) -> Never:
        if reason in _GUESS_REASONS:
            self._throttle.record_failure(source.ip_address, email)
        values: dict[str, str] = {"email": email}
        if reason is not None:
            values["reason"] = reason
        append_audit_log(
            self._db,
            action="login_failed",
            source=source,
            user_id=user.id if user is not None else None,
            user_type=user.user_scope if user is not None else None,
            tenant_id=tenant_id,
            account_id=account_id,
            new_values=values,
        )
        self._db.commit()
        unauthorized("AUTH", message)
