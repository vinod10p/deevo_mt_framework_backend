"""Stateless security helpers — hashing, JWT, token digest, ULIDs.

No FastAPI, SQLAlchemy, Pydantic, or domain imports. Uses ``get_settings()`` only
for JWT secrets, algorithms, and lifetimes.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from passlib.context import CryptContext
from ulid import ULID

from mtf.shared.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

#: ``typ`` claim values. Access and refresh tokens share one key, so the claim is what
#: stops one being accepted where the other is expected.
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


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
    *,
    session_id: str | None = None,
) -> str:
    """Encode a signed access JWT.

    Payload includes ``typ="access"``, ``user_id``, ``user_type``, ``user_scope``,
    ``tenant_id`` (may be JSON null), optional ``account_id`` (portal users), ``sid`` (the
    ``auth.session.id`` — required by ``get_current_user``), ``exp`` (UTC expiry),
    and ``jti`` (new ULID).

    Uses ``jwt_access_token_expire_minutes``, ``jwt_algorithm``, and
    ``jwt_secret_key`` from settings.

    Raises:
        jwt.PyJWTError: If encoding fails (misconfiguration).
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload: dict[str, Any] = {
        "typ": ACCESS_TOKEN_TYPE,
        "user_id": user_id,
        "user_type": user_type,
        "user_scope": user_scope,
        "tenant_id": tenant_id,
        "exp": expire,
        "jti": generate_id(),
    }
    if account_id is not None:
        payload["account_id"] = account_id
    if session_id is not None:
        payload["sid"] = session_id
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(user_id: str, session_id: str) -> str:
    """Encode a signed refresh JWT.

    Claims: ``typ="refresh"``, ``user_id``, ``session_id``, ``exp``, ``jti``.

    Expiry is ``jwt_refresh_token_expire_days`` from settings (UTC). Same algorithm
    and secret as access tokens.

    Raises:
        jwt.PyJWTError: If encoding fails (misconfiguration).
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload: dict[str, Any] = {
        "typ": REFRESH_TOKEN_TYPE,
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
    except InvalidTokenError as exc:
        raise ValueError("TOKEN_INVALID") from exc


def decode_access_token(token: str) -> dict[str, Any]:
    """:func:`decode_token`, then require ``typ == "access"`` (else ``TOKEN_INVALID``)."""
    claims = decode_token(token)
    if claims.get("typ") != ACCESS_TOKEN_TYPE:
        raise ValueError("TOKEN_INVALID")
    return claims


def decode_refresh_token(token: str) -> dict[str, Any]:
    """:func:`decode_token`, then require a refresh token (else ``TOKEN_INVALID``).

    Refresh tokens issued before ``typ`` existed have no claim and are still accepted —
    ``/refresh`` also matches the token's hash to its ``auth.session`` row, so a missing
    ``typ`` cannot let an access token through. Any *other* ``typ`` is rejected.
    """
    claims = decode_token(token)
    if claims.get("typ", REFRESH_TOKEN_TYPE) != REFRESH_TOKEN_TYPE:
        raise ValueError("TOKEN_INVALID")
    return claims


#: ``typ`` claim of the mailbox OAuth ``state`` token.
MAILBOX_OAUTH_STATE_TYPE = "mailbox_oauth_state"
#: How long an admin has to finish the Microsoft consent screen.
MAILBOX_OAUTH_STATE_TTL = timedelta(minutes=10)


def _purpose_key(purpose: str) -> str:
    """Key derived from the JWT secret for one purpose.

    Tokens signed with it fail :func:`decode_token`, so an OAuth ``state`` (which travels
    in URLs and logs) can never be replayed as a Bearer access token.
    """
    secret = get_settings().jwt_secret_key.get_secret_value().encode("utf-8")
    return hmac.new(secret, purpose.encode("utf-8"), hashlib.sha256).hexdigest()


def create_mailbox_oauth_state(tenant_id: str, mailbox_id: str, initiated_by: str) -> str:
    """Signed, short-lived OAuth ``state`` binding the flow to one mailbox and one admin."""
    settings = get_settings()
    payload: dict[str, Any] = {
        "typ": MAILBOX_OAUTH_STATE_TYPE,
        "tid": tenant_id,
        "mbx": mailbox_id,
        "by": initiated_by,
        "exp": datetime.now(timezone.utc) + MAILBOX_OAUTH_STATE_TTL,
        "jti": generate_id(),
    }
    return jwt.encode(
        payload, _purpose_key(MAILBOX_OAUTH_STATE_TYPE), algorithm=settings.jwt_algorithm
    )


def decode_mailbox_oauth_state(state: str) -> dict[str, str]:
    """Verify a ``state`` from :func:`create_mailbox_oauth_state`.

    Returns ``{"tenant_id", "mailbox_id", "initiated_by"}``.

    Raises:
        ValueError: ``STATE_EXPIRED`` past ``exp``; ``STATE_INVALID`` for a bad signature,
            wrong ``typ``, missing claims, or anything else.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            state,
            _purpose_key(MAILBOX_OAUTH_STATE_TYPE),
            algorithms=[settings.jwt_algorithm],
        )
    except ExpiredSignatureError as exc:
        raise ValueError("STATE_EXPIRED") from exc
    except InvalidTokenError as exc:
        raise ValueError("STATE_INVALID") from exc

    if claims.get("typ") != MAILBOX_OAUTH_STATE_TYPE:
        raise ValueError("STATE_INVALID")
    values = {
        "tenant_id": claims.get("tid"),
        "mailbox_id": claims.get("mbx"),
        "initiated_by": claims.get("by"),
    }
    if not all(isinstance(v, str) and v for v in values.values()):
        raise ValueError("STATE_INVALID")
    return values  # type: ignore[return-value]


def hash_token(raw_token: str) -> bytes:
    """Return SHA-256 digest (32 bytes) of the raw token string (UTF-8).

    Intended for ``BINARY(32)`` / ``VARBINARY`` token hashes in ``auth.session``.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).digest()


def generate_id() -> str:
    """Return a new ULID string (26 characters) for primary keys and ``jti``."""
    return str(ULID())
