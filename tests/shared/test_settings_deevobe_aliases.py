"""Settings load Deevobe-style `DB_*` env names."""


import pytest
from pydantic import SecretStr


@pytest.fixture(autouse=True)
def secure_db_tls_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local ``.env`` may trust any DB certificate and allow http origins; production-mode
    tests here are about other settings, so start from a production-safe baseline."""
    monkeypatch.setenv("DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE", "false")
    monkeypatch.setenv("DEEVO_MSSQL_ENCRYPT", "true")
    monkeypatch.setenv("DEEVO_ALLOWED_ORIGINS", '["https://app.example.com"]')
    monkeypatch.delenv("DEEVO_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    from mtf.shared import config as cfg

    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def test_db_server_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_SERVER", "sql.example.test")
    monkeypatch.setenv("DB_NAME", "mydb")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.delenv("DEEVO_MSSQL_SERVER", raising=False)

    from mtf.shared.config import Settings

    s = Settings()
    assert s.mssql_server == "sql.example.test"
    assert s.mssql_database == "mydb"
    assert s.mssql_user == "u"
    assert s.mssql_password == SecretStr("p")


def test_deevo_prefixed_overrides_db_star(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_SERVER", "from-db-server")
    monkeypatch.setenv("DEEVO_MSSQL_SERVER", "from-deevo-server")
    monkeypatch.setenv("DB_NAME", "n")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")

    from mtf.shared.config import Settings

    s = Settings()
    assert s.mssql_server == "from-deevo-server"


def test_minimal_url_matches_deevobe_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_SERVER", "s")
    monkeypatch.setenv("DB_NAME", "d")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
    monkeypatch.setenv("DEEVO_MSSQL_URL_MINIMAL", "true")
    monkeypatch.setenv("DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE", "false")

    from mtf.shared.config import Settings

    uri = Settings(_env_file=None).sqlalchemy_database_uri()
    assert "mssql+pyodbc://" in uri
    assert "Encrypt=" not in uri
    assert "TrustServerCertificate=" not in uri
    assert "driver=ODBC+Driver+17+for+SQL+Server" in uri


# ---------------------------------------------------------------------------
# Mailbox OAuth success redirect
# ---------------------------------------------------------------------------

_STRONG_SECRET = "x" * 48


def test_mailbox_oauth_success_url_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEVO_MAILBOX_OAUTH_SUCCESS_URL", raising=False)
    monkeypatch.delenv("MAILBOX_OAUTH_SUCCESS_URL", raising=False)
    from mtf.shared.config import Settings

    s = Settings(_env_file=None)
    assert s.mailbox_oauth_success_url == "http://localhost:8001/verification"


@pytest.mark.parametrize("name", ["DEEVO_MAILBOX_OAUTH_SUCCESS_URL", "MAILBOX_OAUTH_SUCCESS_URL"])
def test_mailbox_oauth_success_url_from_env(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "https://admin.example.com/verification")
    from mtf.shared.config import Settings

    assert Settings().mailbox_oauth_success_url == "https://admin.example.com/verification"


@pytest.mark.parametrize(
    "url",
    ["http://admin.example.com/verification", "http://localhost:8001/verification", "/x"],
)
def test_mailbox_oauth_success_url_must_be_https_in_production(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DEEVO_ENVIRONMENT", "production")
    monkeypatch.setenv("DEEVO_JWT_SECRET_KEY", _STRONG_SECRET)
    monkeypatch.setenv("DEEVO_MAILBOX_OAUTH_SUCCESS_URL", url)
    from mtf.shared.config import Settings

    with pytest.raises(ValueError, match="DEEVO_MAILBOX_OAUTH_SUCCESS_URL"):
        Settings()


def test_mailbox_oauth_success_url_https_ok_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEVO_ENVIRONMENT", "production")
    monkeypatch.setenv("DEEVO_JWT_SECRET_KEY", _STRONG_SECRET)
    monkeypatch.setenv("DEEVO_MAILBOX_OAUTH_SUCCESS_URL", "https://admin.example.com/v")
    from mtf.shared.config import Settings

    assert Settings().mailbox_oauth_success_url == "https://admin.example.com/v"


def test_mailbox_oauth_http_allowed_outside_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEVO_ENVIRONMENT", "staging")
    monkeypatch.setenv("DEEVO_MAILBOX_OAUTH_SUCCESS_URL", "http://localhost:8001/verification")
    from mtf.shared.config import Settings

    assert Settings().environment == "staging"


# ---------------------------------------------------------------------------
# JWT secret strength (finding #7)
# ---------------------------------------------------------------------------


def _settings(monkeypatch: pytest.MonkeyPatch, env: str, secret: str, alg: str | None = None):
    monkeypatch.setenv("DEEVO_ENVIRONMENT", env)
    monkeypatch.setenv("DEEVO_JWT_SECRET_KEY", secret)
    monkeypatch.setenv("DEEVO_MAILBOX_OAUTH_SUCCESS_URL", "https://admin.example.com/v")
    if alg is None:
        monkeypatch.delenv("DEEVO_JWT_ALGORITHM", raising=False)
        monkeypatch.delenv("JWT_ALGORITHM", raising=False)
    else:
        monkeypatch.setenv("DEEVO_JWT_ALGORITHM", alg)
    from mtf.shared.config import Settings

    return Settings()


@pytest.mark.parametrize(
    "secret",
    ["changeme", "change-me", "CHANGE-ME", " change-me ", "your_secret_key_here", ""],
)
def test_production_rejects_placeholder_secret(
    monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    with pytest.raises(ValueError, match="placeholder"):
        _settings(monkeypatch, "production", secret)


@pytest.mark.parametrize(
    ("alg", "too_short", "just_enough"),
    [("HS256", 31, 32), ("HS384", 47, 48), ("HS512", 63, 64)],
)
def test_production_secret_length_by_algorithm(
    monkeypatch: pytest.MonkeyPatch, alg: str, too_short: int, just_enough: int
) -> None:
    with pytest.raises(ValueError, match=f"shorter than {just_enough} bytes"):
        _settings(monkeypatch, "production", "k" * too_short, alg)
    from mtf.shared import config as cfg

    cfg.get_settings.cache_clear()
    s = _settings(monkeypatch, "production", "k" * just_enough, alg)
    assert s.jwt_algorithm == alg


def test_length_is_measured_in_bytes_not_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    """16 two-byte characters = 32 bytes → enough for HS256."""
    s = _settings(monkeypatch, "production", "é" * 16)
    assert len(s.jwt_secret_key.get_secret_value()) == 16


def test_error_never_echoes_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "short-but-very-identifiable"
    with pytest.raises(ValueError) as exc_info:
        _settings(monkeypatch, "production", secret)
    assert secret not in str(exc_info.value)
    assert "secrets.token_urlsafe" in str(exc_info.value)


@pytest.mark.parametrize("env", ["development", "staging"])
def test_weak_secret_only_warns_outside_production(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, env: str
) -> None:
    secret = "weak-dev-secret"
    with caplog.at_level("WARNING", logger="mtf.shared.config"):
        s = _settings(monkeypatch, env, secret)
    assert s.environment == env
    assert "shorter than 32 bytes" in caplog.text
    assert secret not in caplog.text


def test_strong_secret_does_not_warn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="mtf.shared.config"):
        _settings(monkeypatch, "development", "s" * 64)
    assert "DEEVO_JWT_SECRET_KEY" not in caplog.text


@pytest.mark.parametrize("alg", ["RS256", "none", "hs256", "ES256"])
def test_only_hmac_algorithms_allowed(monkeypatch: pytest.MonkeyPatch, alg: str) -> None:
    with pytest.raises(ValueError, match="jwt_algorithm|JWT_ALGORITHM|Input should be"):
        _settings(monkeypatch, "development", "s" * 64, alg)


# ---------------------------------------------------------------------------
# Database TLS (finding #9)
# ---------------------------------------------------------------------------

_PROD_OK = {
    "DEEVO_ENVIRONMENT": "production",
    "DEEVO_JWT_SECRET_KEY": "p" * 64,
    "DEEVO_MAILBOX_OAUTH_SUCCESS_URL": "https://admin.example.com/v",
}


def _db_settings(monkeypatch: pytest.MonkeyPatch, env: str = "production", **values: str):
    for key, value in {**_PROD_OK, "DEEVO_ENVIRONMENT": env, **values}.items():
        monkeypatch.setenv(key, value)
    from mtf.shared.config import Settings

    return Settings()


@pytest.mark.parametrize(
    "driver", ["ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"]
)
@pytest.mark.parametrize("minimal", ["true", "false"])
def test_production_uri_always_encrypts_and_verifies(
    monkeypatch: pytest.MonkeyPatch, driver: str, minimal: str
) -> None:
    s = _db_settings(
        monkeypatch, DEEVO_MSSQL_ODBC_DRIVER=driver, DEEVO_MSSQL_URL_MINIMAL=minimal
    )
    uri = s.sqlalchemy_database_uri()
    assert uri.count("Encrypt=yes") == 1
    assert uri.count("TrustServerCertificate=no") == 1
    assert "Encrypt=no" not in uri and "TrustServerCertificate=yes" not in uri


def test_production_rejects_trust_server_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE must be false"):
        _db_settings(monkeypatch, DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE="true")


def test_production_rejects_encrypt_off(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="DEEVO_MSSQL_ENCRYPT must be true"):
        _db_settings(monkeypatch, DEEVO_MSSQL_ENCRYPT="false")


def test_production_error_does_not_leak_password(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError) as exc_info:
        _db_settings(
            monkeypatch,
            DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE="true",
            DEEVO_MSSQL_PASSWORD="Sup3r-Secret-Pw",
        )
    assert "Sup3r-Secret-Pw" not in str(exc_info.value)


_BASE_URL = "mssql+pyodbc://u:p@db.example.com:1433/app?driver=ODBC+Driver+18+for+SQL+Server"


@pytest.mark.parametrize(
    "suffix",
    [
        "&Encrypt=yes",
        "&encrypt=YES",
        "&Encrypt=strict",
        "&Encrypt=yes&TrustServerCertificate=no",
        "&odbc_connect=" + "Encrypt%3Dyes%3BTrustServerCertificate%3Dno",
    ],
)
def test_production_database_url_accepted_when_verified(
    monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    s = _db_settings(monkeypatch, DEEVO_DATABASE_URL=_BASE_URL + suffix)
    assert s.sqlalchemy_database_uri() == _BASE_URL + suffix


@pytest.mark.parametrize(
    ("suffix", "match"),
    [
        ("", "must set Encrypt=yes"),
        ("&Encrypt=no", "must set Encrypt=yes"),
        ("&Encrypt=optional", "must set Encrypt=yes"),
        ("&Encrypt=yes&TrustServerCertificate=yes", "must not set TrustServerCertificate"),
        ("&Encrypt=yes&trustservercertificate=TRUE", "must not set TrustServerCertificate"),
        ("&odbc_connect=" + "Encrypt%3Dno", "must set Encrypt=yes"),
        (
            "&odbc_connect=" + "Encrypt%3Dyes%3BTrustServerCertificate%3Dyes",
            "must not set TrustServerCertificate",
        ),
    ],
)
def test_production_database_url_rejected_when_unverified(
    monkeypatch: pytest.MonkeyPatch, suffix: str, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _db_settings(monkeypatch, DEEVO_DATABASE_URL=_BASE_URL + suffix)


@pytest.mark.parametrize("env", ["development", "staging"])
def test_insecure_db_only_warns_outside_production(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, env: str
) -> None:
    with caplog.at_level("WARNING", logger="mtf.shared.config"):
        s = _db_settings(monkeypatch, env, DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE="true")
    assert "TrustServerCertificate=yes" in s.sqlalchemy_database_uri()
    assert "DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE must be false" in caplog.text


def test_dev_warns_when_driver17_minimal_url_is_unencrypted(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="mtf.shared.config"):
        _db_settings(
            monkeypatch,
            "development",
            DEEVO_MSSQL_ODBC_DRIVER="ODBC Driver 17 for SQL Server",
            DEEVO_MSSQL_URL_MINIMAL="true",
        )
    assert "does not encrypt by default" in caplog.text


def test_dev_driver18_minimal_url_is_quiet(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="mtf.shared.config"):
        _db_settings(
            monkeypatch,
            "development",
            DEEVO_MSSQL_ODBC_DRIVER="ODBC Driver 18 for SQL Server",
            DEEVO_MSSQL_URL_MINIMAL="true",
        )
    assert "Database connection" not in caplog.text


def test_dev_uri_unchanged_for_existing_local_setups(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outside production the URL is built exactly as before (no surprise Encrypt=yes)."""
    s = _db_settings(
        monkeypatch,
        "development",
        DEEVO_MSSQL_URL_MINIMAL="true",
        DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE="true",
    )
    uri = s.sqlalchemy_database_uri()
    assert uri.endswith("&TrustServerCertificate=yes")
    assert "Encrypt=" not in uri
