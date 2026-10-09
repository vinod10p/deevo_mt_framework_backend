"""Application settings (pydantic-settings).

Uses **`DEEVO_*`** names and Deevo-compatible aliases (**`DB_SERVER`**, **`DB_USER`**, etc.)
so one **`.env`** can work across CRM and MTF projects.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from typing import Literal, Self
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_JWT_SECRETS = frozenset({"changeme", "change-me", "your_secret_key_here", ""})


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

    # ── Reports (rpt) ─────────────────────────────────────────────────────
    #: Statement timeout (seconds) for every report / lookup proc call.
    #: Env: **`DEEVO_REPORT_QUERY_TIMEOUT_SECONDS`**.
    report_query_timeout_seconds: int = Field(default=60, ge=1)

    # ── JWT ───────────────────────────────────────────────────────────────
    jwt_secret_key: SecretStr = Field(
        default=SecretStr("changeme"),
        validation_alias=AliasChoices("DEEVO_JWT_SECRET_KEY", "JWT_SECRET_KEY"),
    )
    jwt_algorithm: str = Field(
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
        if self.environment == "production":
            secret = self.jwt_secret_key.get_secret_value()
            if secret in _INSECURE_JWT_SECRETS:
                raise ValueError(
                    "DEEVO_JWT_SECRET_KEY must be a strong secret when "
                    "DEEVO_ENVIRONMENT=production"
                )
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
        if not self.mssql_url_minimal:
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
