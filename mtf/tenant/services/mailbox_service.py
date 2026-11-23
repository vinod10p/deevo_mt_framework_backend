"""Service — Mailbox management and Microsoft OAuth authorization."""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Never

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from ulid import ULID

from mtf.audit.service import (
    AuditSource,
    audit_insert,
    audit_soft_delete,
    audit_update,
    row_snapshot,
)
from mtf.shared.config import get_settings
from mtf.shared.deps import CurrentUser
from mtf.shared.exceptions import bad_request
from mtf.shared.security import create_mailbox_oauth_state, decode_mailbox_oauth_state
from mtf.tenant.models.mailbox import Mailbox
from mtf.tenant.models.mailbox_credential import MailboxCredential
from mtf.tenant.schemas.mailbox import MailboxCreate, MailboxUpdate

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
MAILBOX_OAUTH_FAILED_MESSAGE = (
    "Mailbox authorization failed. Please start again from the admin app."
)
MAILBOX_TOKEN_REFRESH_FAILED_MESSAGE = (
    "Mailbox access has expired or was revoked. Please re-authorize the mailbox."
)


def _oauth_fail(log_message: str) -> Never:
    """Log the real reason; return one generic 400 to the browser."""
    logger.warning("Mailbox OAuth callback: %s", log_message)
    bad_request("MAILBOX_OAUTH", MAILBOX_OAUTH_FAILED_MESSAGE)


class MailboxService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._settings = get_settings()

    def list_by_tenant(self, tenant_id: str, skip: int = 0, limit: int = 100) -> list[Mailbox]:
        stmt = (
            select(Mailbox)
            .where(Mailbox.tenant_id == tenant_id, Mailbox.is_deleted == False)
            .order_by(Mailbox.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(self._session.scalars(stmt).all())

    def get_by_id(self, tenant_id: str, mailbox_id: str) -> Mailbox | None:
        stmt = select(Mailbox).where(
            Mailbox.id == mailbox_id,
            Mailbox.tenant_id == tenant_id,
            Mailbox.is_deleted == False,
        )
        return self._session.scalars(stmt).first()

    def create_for_tenant(
        self,
        tenant_id: str,
        payload: MailboxCreate,
        created_by: str | None = None,
        *,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Mailbox:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        mailbox = Mailbox(
            id=str(ULID()),
            tenant_id=tenant_id,
            email_address=payload.email_address,
            display_name=payload.display_name or payload.email_address,
            provider=payload.provider,
            mailbox_type=payload.mailbox_type,
            is_active=payload.is_active,
            is_sync_enabled=True,
            is_deleted=False,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
        )
        self._session.add(mailbox)
        audit_insert(
            self._session,
            entity=mailbox,
            schema_name="email",
            table_name="mailbox",
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(mailbox)
        return mailbox

    def update_for_tenant(
        self,
        tenant_id: str,
        mailbox_id: str,
        payload: MailboxUpdate,
        updated_by: str | None = None,
        *,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> Mailbox | None:
        mailbox = self.get_by_id(tenant_id, mailbox_id)
        if not mailbox:
            return None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        before = row_snapshot(mailbox)
        if payload.display_name is not None:
            mailbox.display_name = payload.display_name
        if payload.mailbox_type is not None:
            mailbox.mailbox_type = payload.mailbox_type
        if payload.is_active is not None:
            mailbox.is_active = payload.is_active
        mailbox.updated_at = now
        mailbox.updated_by = updated_by
        audit_update(
            self._session,
            entity=mailbox,
            schema_name="email",
            table_name="mailbox",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        self._session.commit()
        self._session.refresh(mailbox)
        return mailbox

    def delete_for_tenant(
        self,
        tenant_id: str,
        mailbox_id: str,
        deleted_by: str | None = None,
        *,
        actor: CurrentUser | None = None,
        source: AuditSource | None = None,
    ) -> bool:
        mailbox = self.get_by_id(tenant_id, mailbox_id)
        if not mailbox:
            return False
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        before = row_snapshot(mailbox)
        mailbox.is_deleted = True
        mailbox.deleted_at = now
        mailbox.deleted_by = deleted_by
        audit_soft_delete(
            self._session,
            entity=mailbox,
            schema_name="email",
            table_name="mailbox",
            before=before,
            actor=actor,
            source=source,
            tenant_id=tenant_id,
        )
        self._session.commit()
        return True

    # ---------------------------------------------------------------------------
    # Microsoft OAuth 2.0 Authorization & Token Management
    # ---------------------------------------------------------------------------

    def get_authorization_url(self, tenant_id: str, mailbox_id: str, initiated_by: str) -> str:
        """Microsoft OAuth2 authorization URL with a signed ``state`` (see
        :func:`create_mailbox_oauth_state`) bound to this mailbox and the calling admin."""
        state_str = create_mailbox_oauth_state(tenant_id, mailbox_id, initiated_by)

        params = {
            "client_id": self._settings.microsoft_client_id,
            "response_type": "code",
            "redirect_uri": self._settings.microsoft_redirect_uri,
            "response_mode": "query",
            "scope": "offline_access Mail.ReadWrite User.Read",
            "state": state_str,
            "prompt": "select_account",
        }

        query_string = urllib.parse.urlencode(params)
        return f"{self._settings.microsoft_authority}/oauth2/v2.0/authorize?{query_string}"

    def process_oauth_callback(self, state: str, code: str) -> MailboxCredential:
        """Verify ``state``, exchange ``code``, check the tokens can open this mailbox, persist.

        Every failure raises ``400 MAILBOX_OAUTH_BAD_REQUEST`` with a generic message;
        details (including Microsoft's response) are logged only.
        """
        try:
            flow = decode_mailbox_oauth_state(state)
        except ValueError as exc:
            _oauth_fail(f"rejected state: {exc}")
        tenant_id = flow["tenant_id"]
        mailbox_id = flow["mailbox_id"]
        initiated_by = flow["initiated_by"]

        mailbox = self.get_by_id(tenant_id, mailbox_id)
        if not mailbox:
            _oauth_fail(f"mailbox {mailbox_id} not found for tenant {tenant_id}")

        client_secret = self._settings.microsoft_client_secret.get_secret_value()
        token_url = f"{self._settings.microsoft_authority}/oauth2/v2.0/token"
        data = {
            "client_id": self._settings.microsoft_client_id,
            "scope": "offline_access Mail.ReadWrite User.Read",
            "code": code,
            "redirect_uri": self._settings.microsoft_redirect_uri,
            "grant_type": "authorization_code",
            "client_secret": client_secret,
        }

        response = httpx.post(token_url, data=data, timeout=15)
        if response.status_code != 200:
            _oauth_fail(f"token exchange failed ({response.status_code}): {response.text}")

        token_data = response.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        if not access_token or not refresh_token:
            _oauth_fail("token response missing access_token or refresh_token")

        # The consenting Microsoft account must actually be able to open *this* mailbox —
        # otherwise anyone could bind their own account's tokens to another mailbox record.
        mailbox_url = (
            f"{GRAPH_API_BASE}/users/{urllib.parse.quote(mailbox.email_address, safe='@')}"
            "/mailFolders/inbox?$select=id"
        )
        check = httpx.get(
            mailbox_url, headers={"Authorization": f"Bearer {access_token}"}, timeout=15
        )
        if check.status_code != 200:
            _oauth_fail(
                f"consented account cannot open mailbox {mailbox.email_address} "
                f"({check.status_code}): {check.text}"
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expires_at = now + timedelta(seconds=int(expires_in))

        # Look up existing credential or create new one
        stmt = select(MailboxCredential).where(
            MailboxCredential.mailbox_id == mailbox_id,
            MailboxCredential.tenant_id == tenant_id,
            MailboxCredential.is_deleted == False,
        )
        cred = self._session.scalars(stmt).first()
        user_id = initiated_by

        if not cred:
            cred_id = str(ULID())
            cred = MailboxCredential(
                id=cred_id,
                tenant_id=tenant_id,
                mailbox_id=mailbox_id,
                provider="microsoft_graph",
                auth_mode="delegated",
                credential_ref=cred_id,
                credential_status="active",
                access_token=access_token,
                refresh_token=refresh_token,
                access_token_expires_at=expires_at,
                consented_at=now,
                is_active=True,
                is_deleted=False,
                created_at=now,
                updated_at=now,
                created_by=user_id,
                updated_by=user_id,
            )
            self._session.add(cred)

        else:
            cred.access_token = access_token
            cred.refresh_token = refresh_token
            cred.access_token_expires_at = expires_at
            cred.credential_status = "active"
            cred.consented_at = now
            cred.updated_at = now
            cred.updated_by = user_id


        mailbox.updated_at = now
        self._session.commit()
        self._session.refresh(cred)
        return cred

    def get_valid_access_token(self, tenant_id: str, mailbox_id: str) -> str | None:
        """Get valid access_token for mailbox. Refreshes token automatically if expiring within 5 minutes."""
        stmt = select(MailboxCredential).where(
            MailboxCredential.mailbox_id == mailbox_id,
            MailboxCredential.tenant_id == tenant_id,
            MailboxCredential.is_deleted == False,
        )
        cred = self._session.scalars(stmt).first()
        if not cred or not cred.access_token or not cred.refresh_token:
            return None

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if cred.access_token_expires_at and cred.access_token_expires_at > (now + timedelta(minutes=5)):
            return cred.access_token

        # Token expired or expiring soon — refresh token
        token_url = f"{self._settings.microsoft_authority}/oauth2/v2.0/token"
        client_secret = self._settings.microsoft_client_secret.get_secret_value()
        data = {
            "client_id": self._settings.microsoft_client_id,
            "scope": "offline_access Mail.ReadWrite User.Read",
            "refresh_token": cred.refresh_token,
            "grant_type": "refresh_token",
            "client_secret": client_secret,
        }

        response = httpx.post(token_url, data=data, timeout=15)
        token_data = response.json() if response.status_code == 200 else {}
        new_access_token = token_data.get("access_token")
        if not new_access_token:
            # Microsoft's text stays server-side (DB + log); callers get a generic error.
            cred.credential_status = "error"
            cred.last_error = response.text
            cred.last_error_at = now
            self._session.commit()
            logger.warning(
                "Mailbox token refresh failed for mailbox %s (%s): %s",
                mailbox_id,
                response.status_code,
                response.text,
            )
            bad_request("MAILBOX_TOKEN", MAILBOX_TOKEN_REFRESH_FAILED_MESSAGE)

        new_refresh_token = token_data.get("refresh_token", cred.refresh_token)
        expires_in = token_data.get("expires_in", 3600)

        cred.access_token = new_access_token
        cred.refresh_token = new_refresh_token
        cred.access_token_expires_at = now + timedelta(seconds=int(expires_in))
        cred.last_refreshed_at = now
        cred.credential_status = "active"
        cred.updated_at = now

        self._session.commit()
        return new_access_token

