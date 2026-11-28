"""Pydantic schemas — auth session / token exchange."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CreatedFrom = Literal["web", "mobile_ios", "mobile_android", "desktop", "api"]


class LoginRequest(BaseModel):
    email: str
    password: str
    created_from: CreatedFrom = "web"
    tenant_id: str | None = None
    #: Store typed at login: required for tenant staff, ignored for portal and system users.
    business_unit_code: str | None = Field(None, max_length=30)


class BusinessUnitSwitchRequest(BaseModel):
    """``POST /auth/session/business-unit`` — the store code, typed as at login."""

    business_unit_code: str = Field(..., max_length=30)


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    user_type: str
    user_scope: str
    tenant_id: str | None = None
    account_id: str | None = None
    account_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    tenant_name: str | None = None
    #: The session's business unit (portal users: the tenant root; system users: none).
    business_unit_id: str | None = None
    business_unit_code: str | None = None
    business_unit_name: str | None = None
    business_unit_type: str | None = None
    #: The tenant has more than one active store, so the app shows the store switcher.
    multi_store: bool = False


class BrowserTokenResponse(AccessTokenResponse):
    session_id: str


class TokenResponse(AccessTokenResponse):
    refresh_token: str


class BrowserRefreshRequest(BaseModel):
    refresh_token: str | None = None
    session_id: str | None = None


class BrowserLogoutRequest(BaseModel):
    session_id: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    """Body shape when logging out via JSON; routes may also take raw ``Authorization``."""

    access_token: str = Field(..., description="Raw access JWT (not hashed)")
