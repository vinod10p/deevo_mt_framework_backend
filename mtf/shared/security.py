"""Stateless security helpers — hashing, JWT, token digest, ULIDs.

No FastAPI, SQLAlchemy, Pydantic, or domain imports. Uses ``get_settings()`` only
for JWT secrets, algorithms, and lifetimes.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
from passlib.context import CryptContext
from ulid import ULID

from mtf.shared.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Return a bcrypt hash suitable for storing in ``password_hash``.

    Delegates to passlib ``CryptContext`` (bcrypt).
    """
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if ``plain_password`` matches ``hashed_password``, else False.

    Never raises: malformed or unknown hashes yield False.
    """
    try:
        return _pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def create_access_token(
    user_id: str,
    user_type: str,
    user_scope: str,
    tenant_id: str | None = None,
    account_id: str | None = None,
) -> str:
    """Encode a signed access JWT.

    Payload includes ``user_id``, ``user_type``, ``user_scope``, ``tenant_id`` (may
    be JSON null), optional ``account_id`` (portal users), ``exp`` (UTC expiry),
    and ``jti`` (new ULID).

    Uses ``jwt_access_token_expire_minutes``, ``jwt_algorithm``, and
    ``jwt_secret_key`` from settings.

    Raises:
        jose.JWTError: If encoding fails (misconfiguration).
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload: dict[str, Any] = {
        "user_id": user_id,
        "user_type": user_type,
        "user_scope": user_scope,
        "tenant_id": tenant_id,
        "exp": expire,
        "jti": generate_id(),
    }
    if account_id is not None:
        payload["account_id"] = account_id
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(user_id: str, session_id: str) -> str:
    """Encode a signed refresh JWT with ``user_id``, ``session_id``, ``exp``, ``jti``.

    Expiry is ``jwt_refresh_token_expire_days`` from settings (UTC). Same algorithm
    and secret as access tokens.

    Raises:
        jose.JWTError: If encoding fails (misconfiguration).
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload: dict[str, Any] = {
        "user_id": user_id,
        "session_id": session_id,
        "exp": expire,
        "jti": generate_id(),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT (signature and expiry).

    Returns the claims dict on success. Standard JWT ``exp`` is returned as a
    Unix timestamp (``int``) after decode.

    Raises:
        ValueError: With message ``TOKEN_EXPIRED`` if the token is past ``exp``.
        ValueError: With message ``TOKEN_INVALID`` for bad signature, malformed
            token, wrong algorithm, or any other decode failure.
    """
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except ExpiredSignatureError as exc:
        raise ValueError("TOKEN_EXPIRED") from exc
    except JWTError as exc:
        raise ValueError("TOKEN_INVALID") from exc


def hash_token(raw_token: str) -> bytes:
    """Return SHA-256 digest (32 bytes) of the raw token string (UTF-8).

    Intended for ``BINARY(32)`` / ``VARBINARY`` token hashes in ``auth.session``.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).digest()


def generate_id() -> str:
    """Return a new ULID string (26 characters) for primary keys and ``jti``."""
    return str(ULID())
