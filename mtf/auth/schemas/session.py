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


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
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


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    """Body shape when logging out via JSON; routes may also take raw ``Authorization``."""

    access_token: str = Field(..., description="Raw access JWT (not hashed)")
