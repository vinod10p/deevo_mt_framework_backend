"""Login throttling and the lockout-DoS fix (finding #8) — no database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from mtf.audit.models import AuditLog
from mtf.audit.service import AuditSource
from mtf.auth.api.session import get_session_service
from mtf.auth.schemas.session import LoginRequest
from mtf.auth.services.login_throttle import LoginThrottle
from mtf.auth.services.session_service import SessionService
from mtf.shared.config import get_settings

ATTACKER = AuditSource(ip_address="203.0.113.66", user_agent="evil")
REAL_USER = AuditSource(ip_address="198.51.100.10", user_agent="browser")
EMAIL = "victim@example.com"
_VERIFY = "mtf.auth.services.session_service.verify_password"


def _user(**kwargs: object) -> MagicMock:
    user = MagicMock()
    user.id = "01JUSER0000000000000000001"
    user.user_scope = "system"
    user.password_hash = "hash"
    user.locked_until = None
    user.failed_login_count = 0
    user.first_name, user.last_name = "V", "U"
    for k, v in kwargs.items():
        setattr(user, k, v)
    return user


def _service(user: MagicMock | None, throttle: LoginThrottle) -> tuple[SessionService, MagicMock]:
    db = MagicMock()
    service = SessionService(db, throttle=throttle)
    patch.object(service, "_get_active_user_by_email", return_value=user).start()
    patch.object(service, "_tenant_name", return_value=None).start()
    return service, db


@pytest.fixture(autouse=True)
def _stop_patches():
    yield
    patch.stopall()
    app.dependency_overrides.clear()


def _login(service: SessionService, source: AuditSource, password: str = "guess"):
    return service.login(
        LoginRequest(email=EMAIL, password=password, created_from="web"), source=source
    )


def _attempt(service: SessionService, source: AuditSource, ok: bool) -> int:
    with patch(_VERIFY, return_value=ok):
        try:
            _login(service, source)
            return 200
        except HTTPException as exc:
            return exc.status_code


def test_attacker_ip_is_throttled_after_limit() -> None:
    limit = get_settings().login_max_failures_per_account_ip
    service, db = _service(_user(), LoginThrottle())
    statuses = [_attempt(service, ATTACKER, ok=False) for _ in range(limit + 2)]
    assert statuses == [401] * limit + [429, 429]


def test_throttled_attempt_skips_password_check_and_audit() -> None:
    limit = get_settings().login_max_failures_per_account_ip
    service, db = _service(_user(), LoginThrottle())
    for _ in range(limit):
        _attempt(service, ATTACKER, ok=False)
    audits_before = sum(isinstance(c.args[0], AuditLog) for c in db.add.call_args_list)

    with patch(_VERIFY) as verify, pytest.raises(HTTPException) as exc_info:
        _login(service, ATTACKER)
    verify.assert_not_called()
    audits_after = sum(isinstance(c.args[0], AuditLog) for c in db.add.call_args_list)
    assert audits_after == audits_before
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "AUTH_RATE_LIMITED"
    window = get_settings().login_failure_window_seconds
    assert 1 <= int(exc_info.value.headers["Retry-After"]) <= window


def test_real_user_can_still_log_in_while_attacker_is_blocked() -> None:
    """The lockout-DoS: attacker burns the account's attempts — victim is unaffected."""
    user = _user()
    service, _ = _service(user, LoginThrottle())
    limit = get_settings().login_max_failures_per_account_ip
    for _ in range(limit + 3):
        _attempt(service, ATTACKER, ok=False)

    assert _attempt(service, ATTACKER, ok=True) == 429  # even the right password, from there
    assert user.locked_until is None
    assert _attempt(service, REAL_USER, ok=True) == 200


def test_correct_password_even_with_throttle_resets_per_account_counter() -> None:
    service, _ = _service(_user(), LoginThrottle())
    limit = get_settings().login_max_failures_per_account_ip
    for _ in range(limit - 1):
        _attempt(service, REAL_USER, ok=False)
    assert _attempt(service, REAL_USER, ok=True) == 200
    for _ in range(limit - 1):
        assert _attempt(service, REAL_USER, ok=False) == 401  # counter restarted


def test_account_wide_lockout_only_at_high_threshold() -> None:
    threshold = get_settings().login_account_lockout_threshold
    assert threshold >= 20  # far above the per-IP limit

    user = _user(failed_login_count=threshold - 2)
    service, _ = _service(user, LoginThrottle())
    _attempt(service, ATTACKER, ok=False)
    assert user.locked_until is None
    _attempt(service, ATTACKER, ok=False)
    assert user.locked_until is not None
    expected = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        minutes=get_settings().login_account_lockout_minutes
    )
    assert abs((user.locked_until - expected).total_seconds()) < 5


def test_locked_account_attempts_count_toward_throttle() -> None:
    locked = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)
    service, _ = _service(_user(locked_until=locked), LoginThrottle())
    limit = get_settings().login_max_failures_per_account_ip
    statuses = [_attempt(service, ATTACKER, ok=True) for _ in range(limit + 1)]
    assert statuses == [401] * limit + [429]


def test_unknown_email_counts_toward_throttle() -> None:
    service, _ = _service(None, LoginThrottle())
    limit = get_settings().login_max_failures_per_account_ip
    statuses = [_attempt(service, ATTACKER, ok=False) for _ in range(limit + 1)]
    assert statuses[-1] == 429


def test_password_spray_across_accounts_hits_ip_limit() -> None:
    throttle = LoginThrottle()
    service, _ = _service(None, throttle)
    per_ip = get_settings().login_max_failures_per_ip
    for i in range(per_ip):
        with pytest.raises(HTTPException) as exc_info:
            service.login(
                LoginRequest(email=f"u{i}@example.com", password="x", created_from="web"),
                source=ATTACKER,
            )
        assert exc_info.value.status_code == 401
    with pytest.raises(HTTPException) as exc_info:
        service.login(
            LoginRequest(email="fresh@example.com", password="x", created_from="web"),
            source=ATTACKER,
        )
    assert exc_info.value.status_code == 429


def test_post_password_failures_are_not_counted() -> None:
    """Correct password but missing tenant is a usage error, not a guess."""
    user = _user(user_scope="tenant")
    service, _ = _service(user, LoginThrottle())
    limit = get_settings().login_max_failures_per_account_ip
    statuses = [_attempt(service, REAL_USER, ok=True) for _ in range(limit + 2)]
    assert set(statuses) == {401}  # tenant_required every time, never 429


def test_api_returns_429_with_retry_after_header() -> None:
    throttle = LoginThrottle()
    db = MagicMock()
    service = SessionService(db, throttle=throttle)
    patch.object(service, "_get_active_user_by_email", return_value=None).start()
    app.dependency_overrides[get_session_service] = lambda: service

    client = TestClient(app)
    body = {"email": EMAIL, "password": "nope", "created_from": "web"}
    limit = get_settings().login_max_failures_per_account_ip
    for _ in range(limit):
        assert client.post("/api/auth/login", json=body).status_code == 401
    r = client.post("/api/auth/login", json=body)
    assert r.status_code == 429
    assert r.json()["detail"] == {
        "code": "AUTH_RATE_LIMITED",
        "message": "Too many login attempts. Please try again later.",
    }
    assert int(r.headers["retry-after"]) > 0
