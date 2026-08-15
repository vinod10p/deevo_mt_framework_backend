"""Pydantic schemas — `email.mailbox`."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MailboxRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    email_address: str
    normalized_email: str | None = None
    display_name: str | None = None
    provider: str
    graph_user_id: str | None = None
    mailbox_type: str
    is_sync_enabled: bool
    is_active: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime | None = None


class MailboxCreate(BaseModel):
    email_address: str
    display_name: str | None = None
    mailbox_type: str = "user"
    provider: str = "microsoft_graph"
    is_active: bool = True


class MailboxUpdate(BaseModel):
    display_name: str | None = None
    mailbox_type: str | None = None
    is_active: bool | None = None
