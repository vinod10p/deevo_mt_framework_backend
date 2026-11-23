"""CORS origins and middleware behaviour (finding #10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.shared.config import get_settings

ALLOWED = "http://localhost:3000"
EVIL = "https://evil.example.com"


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Verified DB TLS + strong secrets so production-mode Settings() only tests CORS.
    monkeypatch.setenv("DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE", "false")
    monkeypatch.setenv("DEEVO_MSSQL_ENCRYPT", "true")
    monkeypatch.setenv("DEEVO_JWT_SECRET_KEY", "c" * 64)
    monkeypatch.setenv("DEEVO_MAILBOX_OAUTH_SUCCESS_URL", "https://admin.example.com/v")
    monkeypatch.delenv("DEEVO_DATABASE_URL", raising=False)


def _settings(monkeypatch: pytest.MonkeyPatch, origins: str, env: str = "production"):
    monkeypatch.setenv("DEEVO_ENVIRONMENT", env)
    monkeypatch.setenv("DEEVO_ALLOWED_ORIGINS", origins)
    from mtf.shared.config import Settings

    return Settings()


# ---------------------------------------------------------------------------
# Settings validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origins",
    [
        '["https://app.example.com"]',
        '["https://app.example.com", "https://admin.example.com:8443"]',
        '["https://[2001:db8::1]:8443"]',
        "[]",
    ],
)
def test_production_accepts_exact_https_origins(
    monkeypatch: pytest.MonkeyPatch, origins: str
) -> None:
    _settings(monkeypatch, origins)


@pytest.mark.parametrize(
    ("origins", "match"),
    [
        ('["*"]', "allows every website"),
        ('["https://app.example.com", "*"]', "allows every website"),
        ('["http://app.example.com"]', "is not https"),
        ('["http://localhost:3000"]', "is not https"),
    ],
)
def test_production_rejects_wildcard_and_http(
    monkeypatch: pytest.MonkeyPatch, origins: str, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _settings(monkeypatch, origins)


def test_production_rejects_default_localhost_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """The built-in default is for local dev; production must set its own list."""
    monkeypatch.delenv("DEEVO_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("DEEVO_ENVIRONMENT", "production")
    from mtf.shared.config import Settings

    with pytest.raises(ValueError, match="is not https"):
        Settings(_env_file=None)


@pytest.mark.parametrize("env", ["production", "development"])
@pytest.mark.parametrize(
    "bad",
    [
        "https://app.example.com/",
        "https://app.example.com/login",
        "https://app.example.com?x=1",
        "app.example.com",
        "ftp://app.example.com",
        "https://",
        "https://user:pw@app.example.com",
        "https://app.example.com:99999",
        " https://app.example.com",
    ],
)
def test_malformed_origins_always_rejected(
    monkeypatch: pytest.MonkeyPatch, env: str, bad: str
) -> None:
    """Browsers send a bare origin; anything else silently never matches."""
    with pytest.raises(ValueError, match="DEEVO_ALLOWED_ORIGINS"):
        _settings(monkeypatch, f'["{bad}"]', env)


@pytest.mark.parametrize("env", ["production", "development"])
@pytest.mark.parametrize("null", ["null", "NULL"])
def test_null_origin_always_rejected(monkeypatch: pytest.MonkeyPatch, env: str, null: str) -> None:
    with pytest.raises(ValueError, match="must not contain 'null'"):
        _settings(monkeypatch, f'["{null}"]', env)


def test_wildcard_only_warns_in_development(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="mtf.shared.config"):
        s = _settings(monkeypatch, '["*"]', "development")
    assert s.allowed_origins == ["*"]
    assert "allows every website" in caplog.text


def test_http_localhost_is_quiet_in_development(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="mtf.shared.config"):
        _settings(monkeypatch, '["http://localhost:3000", "http://localhost:8501"]', "development")
    assert "DEEVO_ALLOWED_ORIGINS" not in caplog.text


def test_credentials_setting_defaults_true_and_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEVO_CORS_ALLOW_CREDENTIALS", raising=False)
    assert _settings(monkeypatch, "[]").cors_allow_credentials is True
    monkeypatch.setenv("DEEVO_CORS_ALLOW_CREDENTIALS", "false")
    assert _settings(monkeypatch, "[]").cors_allow_credentials is False


# ---------------------------------------------------------------------------
# Middleware behaviour on the real app
# ---------------------------------------------------------------------------


def _preflight(origin: str, method: str = "POST", headers: str = "authorization,content-type"):
    return TestClient(app).options(
        "/api/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


def test_app_uses_configured_origins() -> None:
    assert ALLOWED in get_settings().allowed_origins


def test_preflight_from_allowed_origin() -> None:
    r = _preflight(ALLOWED)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ALLOWED
    assert "authorization" in r.headers["access-control-allow-headers"].lower()
    allowed_methods = r.headers["access-control-allow-methods"]
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        assert method in allowed_methods


def test_preflight_from_unknown_origin_is_refused() -> None:
    r = _preflight(EVIL)
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("method", ["TRACE", "CONNECT", "PROPFIND"])
def test_unlisted_methods_not_allowed(method: str) -> None:
    r = _preflight(ALLOWED, method=method)
    assert r.status_code == 400


def test_simple_request_from_unknown_origin_gets_no_cors_headers() -> None:
    r = TestClient(app).get("/health", headers={"Origin": EVIL})
    assert r.status_code == 200  # server answers, but the browser won't expose it
    assert "access-control-allow-origin" not in r.headers


def test_allowed_origin_can_read_retry_after() -> None:
    r = TestClient(app).get("/health", headers={"Origin": ALLOWED})
    assert r.headers["access-control-allow-origin"] == ALLOWED
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()


def test_origin_match_is_exact_not_prefix() -> None:
    for sneaky in (ALLOWED + ".evil.com", ALLOWED.replace("http://", "https://"), ALLOWED + "0"):
        r = _preflight(sneaky)
        assert "access-control-allow-origin" not in r.headers, sneaky
