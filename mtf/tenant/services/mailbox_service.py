"""Service — Mailbox management and Microsoft OAuth authorization."""

from __future__ import annotations

import base64
import json
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException
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
from mtf.tenant.models.mailbox import Mailbox
from mtf.tenant.models.mailbox_credential import MailboxCredential
from mtf.tenant.schemas.mailbox import MailboxCreate, MailboxUpdate


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

    def get_authorization_url(self, tenant_id: str, mailbox_id: str) -> str:
        """Generate the Microsoft OAuth2 authorization URL."""
        state_dict = {"tenant_id": tenant_id, "mailbox_id": mailbox_id}
        state_str = base64.urlsafe_b64encode(json.dumps(state_dict).encode()).decode()

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

    def process_oauth_callback(self, tenant_id: str, mailbox_id: str, code: str) -> MailboxCredential | None:
        """Exchange authorization code for access + refresh tokens and persist in email.mailbox_credential."""
        mailbox = self.get_by_id(tenant_id, mailbox_id)
        if not mailbox:
            return None

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
            raise HTTPException(status_code=400, detail=f"Microsoft Token Error: {response.text}")

        token_data = response.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expires_at = now + timedelta(seconds=int(expires_in))

        # Look up existing credential or create new one
        stmt = select(MailboxCredential).where(
            MailboxCredential.mailbox_id == mailbox_id,
            MailboxCredential.tenant_id == tenant_id,
            MailboxCredential.is_deleted == False,
        )
        cred = self._session.scalars(stmt).first()
        user_id = mailbox.created_by or "01HYSTEM00000000000000000"

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
        if response.status_code != 200:
            cred.credential_status = "error"
            cred.last_error = response.text
            cred.last_error_at = now
            self._session.commit()
            raise HTTPException(status_code=400, detail=f"Failed to refresh token: {response.text}")

        token_data = response.json()
        new_access_token = token_data.get("access_token")
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

