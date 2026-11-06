"""Shared FastAPI dependencies for rpt routes."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from fastapi import Depends

from mtf.audit.api.deps import get_audit_source as get_audit_source
from mtf.rpt.execution import open_report_connection
from mtf.shared.deps import CurrentUser, require_any_scope
from mtf.shared.exceptions import forbidden

require_report_user = require_any_scope("tenant", "tenant_account")


def get_report_tenant_id(user: CurrentUser = Depends(require_report_user)) -> str:
    """Tenant id from JWT — must not be taken from the request."""
    if user.tenant_id is None:
        forbidden("AUTH", "Tenant context required")
    return user.tenant_id


def get_report_user(user: CurrentUser = Depends(require_report_user)) -> CurrentUser:
    """Tenant or portal caller with a tenant in the JWT."""
    get_report_tenant_id(user)
    return user


def get_report_connection(
    user: CurrentUser = Depends(require_report_user),
) -> Generator[Any, None, None]:
    """Raw pyodbc connection with ``SESSION_CONTEXT`` set from the JWT, for proc execution."""
    tenant_id = get_report_tenant_id(user)
    with open_report_connection(tenant_id, user.user_id) as conn:
        yield conn
