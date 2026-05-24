"""Reusable HTTPException helpers — consistent ``detail`` shape for every API error.

``detail`` is always ``{"code": "<SCREAMING_SNAKE>", "message": "<human text>"}`` as in CONVENTIONS.md.
"""

from __future__ import annotations

from typing import Any, Never

from fastapi import HTTPException


def _detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def not_found(code_prefix: str, message: str) -> Never:
    """Raise ``404`` with ``{code_prefix}_NOT_FOUND``.

    Example:
        ``not_found("TENANT_USER", "User not found")`` →
        ``404 {"code": "TENANT_USER_NOT_FOUND", "message": "User not found"}``
    """
    raise HTTPException(
        status_code=404,
        detail=_detail(f"{code_prefix}_NOT_FOUND", message),
    )


def conflict(code_prefix: str, message: str) -> Never:
    """Raise ``409`` with ``{code_prefix}_CONFLICT``.

    Example:
        ``conflict("TENANT_CUSTOMER", "Customer code already exists")`` →
        ``409 {"code": "TENANT_CUSTOMER_CONFLICT", "message": "..."}``
    """
    raise HTTPException(
        status_code=409,
        detail=_detail(f"{code_prefix}_CONFLICT", message),
    )


def forbidden(code_prefix: str, message: str) -> Never:
    """Raise ``403`` with ``{code_prefix}_FORBIDDEN``.

    Example:
        ``forbidden("AUTH", "Insufficient permissions")`` →
        ``403 {"code": "AUTH_FORBIDDEN", "message": "..."}``
    """
    raise HTTPException(
        status_code=403,
        detail=_detail(f"{code_prefix}_FORBIDDEN", message),
    )


def unauthorized(code_prefix: str, message: str) -> Never:
    """Raise ``401`` with ``{code_prefix}_UNAUTHORIZED``.

    Example:
        ``unauthorized("AUTH", "Invalid or expired token")`` →
        ``401 {"code": "AUTH_UNAUTHORIZED", "message": "..."}``
    """
    raise HTTPException(
        status_code=401,
        detail=_detail(f"{code_prefix}_UNAUTHORIZED", message),
    )


def bad_request(code_prefix: str, message: str) -> Never:
    """Raise ``400`` with ``{code_prefix}_BAD_REQUEST``.

    Example:
        ``bad_request("TENANT", "Invalid plan type")`` →
        ``400 {"code": "TENANT_BAD_REQUEST", "message": "..."}``
    """
    raise HTTPException(
        status_code=400,
        detail=_detail(f"{code_prefix}_BAD_REQUEST", message),
    )


def row_version_conflict(domain: str) -> Never:
    """Raise ``409`` for optimistic concurrency (``row_version`` mismatch).

    Example:
        ``row_version_conflict("TENANT")`` →
        ``409 {"code": "TENANT_CONFLICT", "message": "Record was modified ..."}``
    """
    msg = (
        "Record was modified by another request. "
        "Fetch the latest version and retry."
    )
    raise HTTPException(
        status_code=409,
        detail=_detail(f"{domain}_CONFLICT", msg),
    )


def raise_if_not_found(record: Any, code_prefix: str, message: str) -> None:
    """Call :func:`not_found` when ``record`` is ``None``.

    Example:
        ``raise_if_not_found(tenant, "TENANT", "Tenant not found")`` —
        raises ``404`` if ``tenant`` is ``None``; otherwise returns normally.
    """
    if record is None:
        not_found(code_prefix, message)
