"""Application settings (pydantic-settings).

Uses **`DEEVO_*`** names and Deevo-compatible aliases (**`DB_SERVER`**, **`DB_USER`**, etc.)
so one **`.env`** can work across CRM and MTF projects.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from typing import Literal, Self
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_JWT_SECRETS = frozenset({"changeme", "change-me", "your_secret_key_here", ""})

#: Only symmetric HMAC algorithms are supported (one shared secret signs and verifies).
JwtAlgorithm = Literal["HS256", "HS384", "HS512"]
#: RFC 7518 §3.2 — the HMAC key must be at least the size of the hash output.
JWT_MIN_SECRET_BYTES: dict[str, int] = {"HS256": 32, "HS384": 48, "HS512": 64}

logger = logging.getLogger(__name__)

_TLS_ON = frozenset({"yes", "true", "mandatory", "strict"})
_TRUST_ON = frozenset({"yes", "true"})


def _odbc_options(database_url: str) -> dict[str, str]:
    """Lower-cased ODBC options from a SQLAlchemy URL: query params and ``odbc_connect``."""
    from urllib.parse import unquote_plus

    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    options: dict[str, str] = {}
    for key, value in url.query.items():
        value = value[-1] if isinstance(value, tuple) else value
        if key.lower() == "odbc_connect":
            for part in unquote_plus(value).split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    options[k.strip().lower()] = v.strip().strip("{}").lower()
        else:
            options[key.lower()] = str(value).lower()
    return options


def _driver_encrypts_by_default(driver: str) -> bool:
    """ODBC Driver 18+ encrypts unless told not to; 17 and older do not."""
    import re

    match = re.search(r"ODBC Driver (\d+)", driver, re.IGNORECASE)
    return bool(match) and int(match.group(1)) >= 18


def _package_version() -> str:
    try:
        return version("deevo-mt-framework-backend")
    except PackageNotFoundError:
        return "0.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEEVO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ── App ───────────────────────────────────────────────────────────────
    app_name: str = Field(
        default="Deevo MT Framework",
        validation_alias=AliasChoices("DEEVO_APP_NAME", "APP_NAME"),
    )
    app_version: str = Field(default_factory=_package_version)
    debug: bool = Field(
        default=False,
        validation_alias=AliasChoices("DEEVO_DEBUG", "DEBUG"),
    )
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("DEEVO_ENVIRONMENT", "ENVIRONMENT"),
    )
    allowed_origins: list[str] = Field(
        default=[
            "http://localhost:3000",   # deevo_crm
            "http://localhost:3001",   # deevo_portal
            "http://localhost:8501",   # deevo_admin streamlit
            "http://localhost:8502",   # deevo_account_st streamlit
        ],
        validation_alias=AliasChoices("DEEVO_ALLOWED_ORIGINS", "ALLOWED_ORIGINS"),
    )
    #: ``Access-Control-Allow-Credentials``. Auth is Bearer-only (no cookies), so clients
    #: need this only if they send ``withCredentials`` / ``credentials: "include"``.
    cors_allow_credentials: bool = Field(
        default=True,
        validation_alias=AliasChoices("DEEVO_CORS_ALLOW_CREDENTIALS", "CORS_ALLOW_CREDENTIALS"),
    )
    skip_db_tests: bool = Field(
        default=False,
        validation_alias=AliasChoices("DEEVO_SKIP_DB_TESTS", "SKIP_DB_TESTS"),
    )

    # ── Database ──────────────────────────────────────────────────────────
    #: Full SQLAlchemy URL (overrides MSSQL fields). Also **`DATABASE_URL`** (no prefix).
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DEEVO_DATABASE_URL", "DATABASE_URL"),
    )

    mssql_server: str = Field(
        default="localhost",
        validation_alias=AliasChoices("DEEVO_MSSQL_SERVER", "DB_SERVER"),
    )
    mssql_port: int = Field(
        default=1433,
        validation_alias=AliasChoices("DEEVO_MSSQL_PORT", "DB_PORT"),
    )
    mssql_database: str = Field(
        default="deevo_mt",
        validation_alias=AliasChoices("DEEVO_MSSQL_DATABASE", "DB_NAME"),
    )
    mssql_user: str = Field(
        default="deevo_app",
        validation_alias=AliasChoices("DEEVO_MSSQL_USER", "DB_USER"),
    )
    mssql_password: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("DEEVO_MSSQL_PASSWORD", "DB_PASSWORD"),
    )
    #: Must match a name from `odbcinst -q -d` (e.g. **ODBC Driver 17 for SQL Server**).
    mssql_odbc_driver: str = Field(
        default="ODBC Driver 17 for SQL Server",
        validation_alias=AliasChoices("DEEVO_MSSQL_ODBC_DRIVER", "DB_DRIVER"),
    )
    mssql_url_minimal: bool = Field(
        default=True,
        validation_alias=AliasChoices("DEEVO_MSSQL_URL_MINIMAL", "MSSQL_URL_MINIMAL"),
    )
    mssql_encrypt: bool = Field(
        default=True,
        validation_alias=AliasChoices("DEEVO_MSSQL_ENCRYPT", "MSSQL_ENCRYPT"),
    )
    mssql_trust_server_certificate: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE",
            "MSSQL_TRUST_SERVER_CERTIFICATE",
        ),
    )

    # ── Login throttling (in-memory, per worker) ──────────────────────────
    #: Failed logins from one IP (any accounts) before that IP gets 429.
    login_max_failures_per_ip: int = Field(default=30, ge=1)
    #: Failed logins for one account from one IP before that pair gets 429.
    login_max_failures_per_account_ip: int = Field(default=5, ge=1)
    #: Sliding window for both counters above.
    login_failure_window_seconds: int = Field(default=900, ge=1)
    #: Account-wide lockout (all IPs) — high, so one attacker can't lock a user out.
    login_account_lockout_threshold: int = Field(default=50, ge=1)
    login_account_lockout_minutes: int = Field(default=15, ge=1)
    #: Reverse proxies whose ``X-Forwarded-For`` is trusted (IPs or CIDRs, JSON list).
    #: Empty = use the socket peer address. Env: ``DEEVO_TRUSTED_PROXIES``.
    trusted_proxies: list[str] = Field(default_factory=list)

    # ── Reports (rpt) ─────────────────────────────────────────────────────
    #: Statement timeout (seconds) for every report / lookup proc call.
    #: Env: **`DEEVO_REPORT_QUERY_TIMEOUT_SECONDS`**.
    report_query_timeout_seconds: int = Field(default=60, ge=1)

    # ── JWT ───────────────────────────────────────────────────────────────
    jwt_secret_key: SecretStr = Field(
        default=SecretStr("changeme"),
        validation_alias=AliasChoices("DEEVO_JWT_SECRET_KEY", "JWT_SECRET_KEY"),
    )
    jwt_algorithm: JwtAlgorithm = Field(
        default="HS256",
        validation_alias=AliasChoices("DEEVO_JWT_ALGORITHM", "JWT_ALGORITHM"),
    )
    jwt_access_token_expire_minutes: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "DEEVO_JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
            "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        ),
    )
    jwt_refresh_token_expire_days: int = Field(
        default=7,
        validation_alias=AliasChoices(
            "DEEVO_JWT_REFRESH_TOKEN_EXPIRE_DAYS",
            "JWT_REFRESH_TOKEN_EXPIRE_DAYS",
        ),
    )

    # ── Microsoft OAuth ───────────────────────────────────────────────────
    microsoft_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("DEEVO_MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_ID"),
    )
    microsoft_client_secret: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("DEEVO_MICROSOFT_CLIENT_SECRET", "MICROSOFT_CLIENT_SECRET"),
    )
    microsoft_authority: str = Field(
        default="https://login.microsoftonline.com/common",
        validation_alias=AliasChoices("DEEVO_MICROSOFT_AUTHORITY", "MICROSOFT_AUTHORITY"),
    )
    microsoft_redirect_uri: str = Field(
        default="http://localhost:8000/api/tenant/mailboxes/callback",
        validation_alias=AliasChoices("DEEVO_MICROSOFT_REDIRECT_URI", "MICROSOFT_REDIRECT_URI"),
    )
    #: Where the browser lands after a successful mailbox authorization (admin app page).
    mailbox_oauth_success_url: str = Field(
        default="http://localhost:8001/verification",
        validation_alias=AliasChoices(
            "DEEVO_MAILBOX_OAUTH_SUCCESS_URL", "MAILBOX_OAUTH_SUCCESS_URL"
        ),
    )


    @model_validator(mode="after")
    def split_server_and_port(self) -> Self:
        """Support CRM-style ``DB_SERVER=host,1433`` in a single variable."""
        if "," in self.mssql_server:
            host, port_str = self.mssql_server.rsplit(",", 1)
            host = host.strip()
            port_str = port_str.strip()
            if host and port_str.isdigit():
                object.__setattr__(self, "mssql_server", host)
                object.__setattr__(self, "mssql_port", int(port_str))
        return self

    @model_validator(mode="after")
    def reject_insecure_jwt_in_production(self) -> Self:
        """Placeholder or too-short HMAC secrets: fatal in production, a warning elsewhere.

        Minimum length follows RFC 7518 §3.2 (key at least as long as the hash output).
        Never logs or echoes the secret itself.
        """
        secret = self.jwt_secret_key.get_secret_value()
        min_bytes = JWT_MIN_SECRET_BYTES[self.jwt_algorithm]
        problem: str | None = None
        if secret.strip().lower() in _INSECURE_JWT_SECRETS:
            problem = "is a placeholder value"
        elif len(secret.encode("utf-8")) < min_bytes:
            problem = f"is shorter than {min_bytes} bytes (required for {self.jwt_algorithm})"

        if problem is None:
            return self
        message = (
            f"DEEVO_JWT_SECRET_KEY {problem}. Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )
        if self.environment == "production":
            raise ValueError(message)
        logger.warning("%s (allowed because DEEVO_ENVIRONMENT=%s)", message, self.environment)
        return self

    @model_validator(mode="after")
    def validate_trusted_proxies(self) -> Self:
        import ipaddress

        for value in self.trusted_proxies:
            try:
                ipaddress.ip_network(value.strip(), strict=False)
            except ValueError as exc:
                raise ValueError(
                    f"DEEVO_TRUSTED_PROXIES entry {value!r} is not an IP or CIDR"
                ) from exc
        return self

    @model_validator(mode="after")
    def validate_allowed_origins(self) -> Self:
        """Each CORS origin must be exactly ``scheme://host[:port]``.

        Always fatal: malformed entries (path, trailing ``/``, bad scheme) — browsers send
        the bare origin, so such an entry silently never matches. Production also rejects
        ``*``, ``null`` and ``http://`` origins; elsewhere ``*`` only warns.
        """
        from urllib.parse import urlsplit

        insecure: list[str] = []
        for origin in self.allowed_origins:
            if origin == "*":
                insecure.append("'*' allows every website")
                continue
            if origin.lower() == "null":
                raise ValueError(
                    "DEEVO_ALLOWED_ORIGINS must not contain 'null' "
                    "(sandboxed iframes and file:// pages send it)"
                )
            try:
                parts = urlsplit(origin)
                _ = parts.port  # raises ValueError on a bad port
            except ValueError as exc:
                raise ValueError(f"DEEVO_ALLOWED_ORIGINS entry {origin!r} is invalid") from exc
            bare = f"{parts.scheme}://{parts.netloc}"
            if (
                parts.scheme not in ("http", "https")
                or not parts.hostname
                or parts.username is not None
                or origin != bare
            ):
                raise ValueError(
                    f"DEEVO_ALLOWED_ORIGINS entry {origin!r} must be exactly "
                    "scheme://host[:port] (no path, query or trailing slash)"
                )
            if parts.scheme != "https":
                insecure.append(f"{origin!r} is not https")

        if not insecure:
            return self
        message = "DEEVO_ALLOWED_ORIGINS: " + "; ".join(insecure)
        if self.environment == "production":
            raise ValueError(message)
        if "*" in self.allowed_origins:
            logger.warning("%s (allowed because DEEVO_ENVIRONMENT=%s)", message, self.environment)
        return self

    @model_validator(mode="after")
    def require_https_mailbox_redirect_in_production(self) -> Self:
        if self.environment == "production" and not self.mailbox_oauth_success_url.startswith(
            "https://"
        ):
            raise ValueError(
                "DEEVO_MAILBOX_OAUTH_SUCCESS_URL must be an https:// URL when "
                "DEEVO_ENVIRONMENT=production"
            )
        return self

    @model_validator(mode="after")
    def require_verified_db_tls_in_production(self) -> Self:
        """Production: SQL Server traffic must be encrypted *and* the certificate verified.

        Elsewhere an unencrypted / unverified connection is allowed with a warning.
        """
        problems: list[str] = []
        if self.database_url:
            opts = _odbc_options(self.database_url)
            if opts.get("encrypt") not in _TLS_ON:
                problems.append("DEEVO_DATABASE_URL must set Encrypt=yes")
            if opts.get("trustservercertificate") in _TRUST_ON:
                problems.append("DEEVO_DATABASE_URL must not set TrustServerCertificate=yes")
        else:
            if self.mssql_trust_server_certificate:
                problems.append("DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE must be false")
            if not self.mssql_encrypt:
                problems.append("DEEVO_MSSQL_ENCRYPT must be true")
            elif self.mssql_url_minimal and not _driver_encrypts_by_default(
                self.mssql_odbc_driver
            ):
                # Only a risk outside production: production always writes Encrypt=yes.
                if self.environment != "production":
                    problems.append(
                        f"{self.mssql_odbc_driver!r} does not encrypt by default and "
                        "DEEVO_MSSQL_URL_MINIMAL=true omits Encrypt"
                    )

        if not problems:
            return self
        message = "Database connection is not encrypted and verified: " + "; ".join(problems)
        if self.environment == "production":
            raise ValueError(message)
        logger.warning("%s (allowed because DEEVO_ENVIRONMENT=%s)", message, self.environment)
        return self

    def sqlalchemy_database_uri(self) -> str:
        if self.database_url:
            return self.database_url

        pwd = self.mssql_password.get_secret_value()
        driver = quote_plus(self.mssql_odbc_driver)
        user_enc = quote_plus(self.mssql_user)
        pwd_enc = quote_plus(pwd)

        base = (
            f"mssql+pyodbc://{user_enc}:{pwd_enc}@{self.mssql_server}:{self.mssql_port}/"
            f"{self.mssql_database}?driver={driver}"
        )

        extra_params: list[str] = []
        if self.environment == "production":
            # Always explicit, whatever the driver's default (Driver 17 defaults to no TLS).
            # The validator above guarantees encrypt=True and trust=False here.
            extra_params.extend(["Encrypt=yes", "TrustServerCertificate=no"])
        elif not self.mssql_url_minimal:
            enc = "yes" if self.mssql_encrypt else "no"
            tsc = "yes" if self.mssql_trust_server_certificate else "no"
            extra_params.extend([f"Encrypt={enc}", f"TrustServerCertificate={tsc}"])
        else:
            # Minimal URL omits Encrypt by default; still honour explicit trust / no-encrypt.
            if self.mssql_trust_server_certificate:
                extra_params.append("TrustServerCertificate=yes")
            if not self.mssql_encrypt:
                extra_params.append("Encrypt=no")

        if not extra_params:
            return base
        return f"{base}&{'&'.join(extra_params)}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
