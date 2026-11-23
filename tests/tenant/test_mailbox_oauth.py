"""Mailbox Microsoft OAuth — ``/authorize`` and ``/mailboxes/callback`` (no database).

Covers the fix for the forgeable ``state`` / unauthenticated ``/authorize`` issue: an
outsider must not be able to bind their own Microsoft tokens to another tenant's mailbox.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.parse
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from main import app
from mtf.shared import security
from mtf.shared.config import get_settings
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.tenant.api.tenant import get_mailbox_service
from mtf.tenant.models.mailbox import Mailbox
from mtf.tenant.models.mailbox_credential import MailboxCredential
from mtf.tenant.services.mailbox_service import (
    GRAPH_API_BASE,
    MAILBOX_OAUTH_FAILED_MESSAGE,
    MailboxService,
)
from tests.tenant.conftest import TEST_SYSTEM_USER_ID, TEST_TENANT_ID, TEST_USER_ID

MAILBOX_ID = "01HZYJZGXM0KV0K4T8Y9MBX001"
OTHER_TENANT_ID = "01HZYJZGXM0KV0K4T8Y9OTHER1"
MAILBOX_EMAIL = "sales@victim.example"
AUTHORIZE_URL = f"/api/tenant/{TEST_TENANT_ID}/mailboxes/{MAILBOX_ID}/authorize"
CALLBACK_URLS = ["/api/tenant/mailboxes/callback", "/api/v1/mailboxes/callback"]
MS_SECRET_TEXT = "AADSTS70008: secret-internal-detail"

_HTTPX = "mtf.tenant.services.mailbox_service.httpx"


def _mailbox(**kwargs: object) -> Mailbox:
    base: dict[str, object] = {
        "id": MAILBOX_ID,
        "tenant_id": TEST_TENANT_ID,
        "email_address": MAILBOX_EMAIL,
        "display_name": "Sales",
        "provider": "microsoft_graph",
        "mailbox_type": "user",
        "is_sync_enabled": True,
        "is_active": True,
        "is_deleted": False,
        "created_by": "01HZYJZGXM0KV0K4T8Y9CREATR",
    }
    base.update(kwargs)
    return Mailbox(**base)


def _response(status_code: int, payload: dict | None = None, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = payload or {}
    r.text = text or json.dumps(payload or {})
    return r


def _token_ok() -> MagicMock:
    return _response(
        200, {"access_token": "ms-access", "refresh_token": "ms-refresh", "expires_in": 3600}
    )


def _valid_state(
    tenant_id: str = TEST_TENANT_ID,
    mailbox_id: str = MAILBOX_ID,
    initiated_by: str = TEST_SYSTEM_USER_ID,
) -> str:
    return security.create_mailbox_oauth_state(tenant_id, mailbox_id, initiated_by)


def _as(scope: str, tenant_id: str | None = None) -> None:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=TEST_SYSTEM_USER_ID if scope == "system" else TEST_USER_ID,
        user_type="app_user",
        user_scope=scope,  # type: ignore[arg-type]
        tenant_id=tenant_id,
    )


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.scalars.return_value.first.return_value = None  # no existing credential
    return session


@pytest.fixture
def service(db: MagicMock) -> Iterator[MailboxService]:
    svc = MailboxService(db)
    app.dependency_overrides[get_mailbox_service] = lambda: svc
    yield svc


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, follow_redirects=False)


def _assert_nothing_persisted(db: MagicMock) -> None:
    db.add.assert_not_called()
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# /authorize
# ---------------------------------------------------------------------------


def test_authorize_requires_bearer(client: TestClient, service: MailboxService) -> None:
    r = client.get(AUTHORIZE_URL)
    assert r.status_code in (401, 403)
    assert "location" not in r.headers


@pytest.mark.parametrize("scope", ["tenant", "tenant_account"])
def test_authorize_rejects_non_system_scope(
    client: TestClient, service: MailboxService, scope: str
) -> None:
    _as(scope, tenant_id=TEST_TENANT_ID)
    with patch.object(service, "get_by_id", return_value=_mailbox()) as get_by_id:
        r = client.get(AUTHORIZE_URL)
    assert r.status_code == 403
    get_by_id.assert_not_called()


def test_authorize_returns_signed_consent_url(
    client: TestClient, service: MailboxService
) -> None:
    _as("system")
    with patch.object(service, "get_by_id", return_value=_mailbox()):
        r = client.get(AUTHORIZE_URL)

    assert r.status_code == 200
    url = r.json()["authorization_url"]
    settings = get_settings()
    assert url.startswith(f"{settings.microsoft_authority}/oauth2/v2.0/authorize?")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["redirect_uri"] == [settings.microsoft_redirect_uri]
    assert query["response_type"] == ["code"]
    assert security.decode_mailbox_oauth_state(query["state"][0]) == {
        "tenant_id": TEST_TENANT_ID,
        "mailbox_id": MAILBOX_ID,
        "initiated_by": TEST_SYSTEM_USER_ID,
    }


def test_authorize_unknown_mailbox_404(client: TestClient, service: MailboxService) -> None:
    _as("system")
    with patch.object(service, "get_by_id", return_value=None):
        r = client.get(AUTHORIZE_URL)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "MAILBOX_NOT_FOUND"


# ---------------------------------------------------------------------------
# /callback — attacks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("callback", CALLBACK_URLS)
def test_callback_rejects_legacy_forged_state(
    client: TestClient, service: MailboxService, db: MagicMock, callback: str
) -> None:
    """The original attack: base64 JSON naming any tenant/mailbox."""
    forged = base64.urlsafe_b64encode(
        json.dumps({"tenant_id": TEST_TENANT_ID, "mailbox_id": MAILBOX_ID}).encode()
    ).decode()
    with patch(_HTTPX) as httpx_mock, patch.object(service, "get_by_id") as get_by_id:
        r = client.get(callback, params={"code": "attacker-code", "state": forged})

    assert r.status_code == 400
    assert r.json()["detail"] == {
        "code": "MAILBOX_OAUTH_BAD_REQUEST",
        "message": MAILBOX_OAUTH_FAILED_MESSAGE,
    }
    httpx_mock.post.assert_not_called()  # code never exchanged
    get_by_id.assert_not_called()
    _assert_nothing_persisted(db)


@pytest.mark.parametrize(
    "state",
    [
        "",
        "garbage",
        "a.b.c",
        security.create_access_token(TEST_SYSTEM_USER_ID, "app_user", "system", None),
    ],
    ids=["empty", "garbage", "fake-jwt", "access-token"],
)
def test_callback_rejects_invalid_state(
    client: TestClient, service: MailboxService, db: MagicMock, state: str
) -> None:
    with patch(_HTTPX) as httpx_mock:
        r = client.get(CALLBACK_URLS[0], params={"code": "c", "state": state})
    assert r.status_code in (400, 422)
    httpx_mock.post.assert_not_called()
    _assert_nothing_persisted(db)


def test_callback_rejects_expired_state(
    client: TestClient, service: MailboxService, db: MagicMock
) -> None:
    expired = jwt.encode(
        {
            "typ": security.MAILBOX_OAUTH_STATE_TYPE,
            "tid": TEST_TENANT_ID,
            "mbx": MAILBOX_ID,
            "by": TEST_SYSTEM_USER_ID,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        security._purpose_key(security.MAILBOX_OAUTH_STATE_TYPE),
        algorithm=get_settings().jwt_algorithm,
    )
    with patch(_HTTPX) as httpx_mock:
        r = client.get(CALLBACK_URLS[0], params={"code": "c", "state": expired})
    assert r.status_code == 400
    httpx_mock.post.assert_not_called()
    _assert_nothing_persisted(db)


def test_callback_state_for_unknown_mailbox_rejected(
    client: TestClient, service: MailboxService, db: MagicMock
) -> None:
    """A valid state whose mailbox was deleted (or belongs to another tenant) fails."""
    state = _valid_state(tenant_id=OTHER_TENANT_ID)
    with patch(_HTTPX) as httpx_mock, patch.object(service, "get_by_id", return_value=None) as g:
        r = client.get(CALLBACK_URLS[0], params={"code": "c", "state": state})
    assert r.status_code == 400
    g.assert_called_once_with(OTHER_TENANT_ID, MAILBOX_ID)
    httpx_mock.post.assert_not_called()
    _assert_nothing_persisted(db)


def test_callback_rejects_account_that_cannot_open_mailbox(
    client: TestClient, service: MailboxService, db: MagicMock
) -> None:
    """Real state, but the consenting Microsoft account is not this mailbox's owner."""
    with (
        patch(_HTTPX) as httpx_mock,
        patch.object(service, "get_by_id", return_value=_mailbox()),
    ):
        httpx_mock.post.return_value = _token_ok()
        httpx_mock.get.return_value = _response(403, text='{"error":"ErrorAccessDenied"}')
        r = client.get(CALLBACK_URLS[0], params={"code": "c", "state": _valid_state()})

    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "MAILBOX_OAUTH_BAD_REQUEST"
    url = httpx_mock.get.call_args.args[0]
    assert url == f"{GRAPH_API_BASE}/users/{MAILBOX_EMAIL}/mailFolders/inbox?$select=id"
    assert httpx_mock.get.call_args.kwargs["headers"] == {"Authorization": "Bearer ms-access"}
    _assert_nothing_persisted(db)


def test_callback_token_error_is_not_leaked(
    client: TestClient,
    service: MailboxService,
    db: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch(_HTTPX) as httpx_mock,
        patch.object(service, "get_by_id", return_value=_mailbox()),
        caplog.at_level(logging.WARNING, logger="mtf.tenant.services.mailbox_service"),
    ):
        httpx_mock.post.return_value = _response(400, text=MS_SECRET_TEXT)
        r = client.get(CALLBACK_URLS[0], params={"code": "c", "state": _valid_state()})

    assert r.status_code == 400
    assert MS_SECRET_TEXT not in r.text
    assert MS_SECRET_TEXT in caplog.text  # still available to operators
    httpx_mock.get.assert_not_called()
    _assert_nothing_persisted(db)


@pytest.mark.parametrize(
    "payload",
    [{"refresh_token": "r"}, {"access_token": "a"}, {}],
    ids=["no-access", "no-refresh", "empty"],
)
def test_callback_incomplete_token_response_rejected(
    client: TestClient, service: MailboxService, db: MagicMock, payload: dict
) -> None:
    with (
        patch(_HTTPX) as httpx_mock,
        patch.object(service, "get_by_id", return_value=_mailbox()),
    ):
        httpx_mock.post.return_value = _response(200, payload)
        r = client.get(CALLBACK_URLS[0], params={"code": "c", "state": _valid_state()})
    assert r.status_code == 400
    _assert_nothing_persisted(db)


def test_state_token_cannot_be_used_as_bearer(client: TestClient) -> None:
    r = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {_valid_state()}"}
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# /callback — happy path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("callback", CALLBACK_URLS)
def test_callback_success_creates_credential(
    client: TestClient, service: MailboxService, db: MagicMock, callback: str
) -> None:
    mailbox = _mailbox()
    with (
        patch(_HTTPX) as httpx_mock,
        patch.object(service, "get_by_id", return_value=mailbox) as get_by_id,
    ):
        httpx_mock.post.return_value = _token_ok()
        httpx_mock.get.return_value = _response(200, {"id": "inbox-id"})
        r = client.get(callback, params={"code": "good-code", "state": _valid_state()})

    assert r.status_code == 307
    assert r.headers["location"].endswith("/verification")
    get_by_id.assert_called_once_with(TEST_TENANT_ID, MAILBOX_ID)
    assert httpx_mock.post.call_args.kwargs["data"]["code"] == "good-code"

    db.add.assert_called_once()
    cred = db.add.call_args.args[0]
    assert isinstance(cred, MailboxCredential)
    assert (cred.tenant_id, cred.mailbox_id) == (TEST_TENANT_ID, MAILBOX_ID)
    assert (cred.access_token, cred.refresh_token) == ("ms-access", "ms-refresh")
    assert cred.created_by == TEST_SYSTEM_USER_ID  # the admin who started the flow
    db.commit.assert_called_once()


def test_callback_success_updates_existing_credential(
    client: TestClient, service: MailboxService, db: MagicMock
) -> None:
    existing = MailboxCredential(
        id="01HZYJZGXM0KV0K4T8Y9CRED01",
        tenant_id=TEST_TENANT_ID,
        mailbox_id=MAILBOX_ID,
        access_token="old",
        refresh_token="old",
        credential_status="error",
    )
    db.scalars.return_value.first.return_value = existing
    with (
        patch(_HTTPX) as httpx_mock,
        patch.object(service, "get_by_id", return_value=_mailbox()),
    ):
        httpx_mock.post.return_value = _token_ok()
        httpx_mock.get.return_value = _response(200, {"id": "inbox-id"})
        r = client.get(CALLBACK_URLS[0], params={"code": "c", "state": _valid_state()})

    assert r.status_code == 307
    db.add.assert_not_called()
    assert (existing.access_token, existing.refresh_token) == ("ms-access", "ms-refresh")
    assert existing.credential_status == "active"
    assert existing.updated_by == TEST_SYSTEM_USER_ID
    db.commit.assert_called_once()


def test_full_flow_authorize_then_callback(
    client: TestClient, service: MailboxService, db: MagicMock
) -> None:
    """The state handed out by /authorize is exactly what /callback accepts."""
    _as("system")
    with (
        patch(_HTTPX) as httpx_mock,
        patch.object(service, "get_by_id", return_value=_mailbox()),
    ):
        url = client.get(AUTHORIZE_URL).json()["authorization_url"]
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        app.dependency_overrides.pop(get_current_user)  # Microsoft's redirect has no Bearer

        httpx_mock.post.return_value = _token_ok()
        httpx_mock.get.return_value = _response(200, {"id": "inbox-id"})
        r = client.get(CALLBACK_URLS[0], params={"code": "c", "state": state})

    assert r.status_code == 307
    db.commit.assert_called_once()


def test_callback_redirects_to_configured_success_url(
    client: TestClient, service: MailboxService, db: MagicMock
) -> None:
    settings = get_settings().model_copy(
        update={"mailbox_oauth_success_url": "https://admin.example.com/mailbox-ok"}
    )
    with (
        patch(_HTTPX) as httpx_mock,
        patch.object(service, "get_by_id", return_value=_mailbox()),
        patch("mtf.tenant.api.tenant.get_settings", return_value=settings),
    ):
        httpx_mock.post.return_value = _token_ok()
        httpx_mock.get.return_value = _response(200, {"id": "inbox-id"})
        r = client.get(CALLBACK_URLS[0], params={"code": "c", "state": _valid_state()})

    assert r.status_code == 307
    assert r.headers["location"] == "https://admin.example.com/mailbox-ok"


def test_failed_callback_never_redirects(
    client: TestClient, service: MailboxService, db: MagicMock
) -> None:
    r = client.get(CALLBACK_URLS[0], params={"code": "c", "state": "bad"})
    assert r.status_code == 400
    assert "location" not in r.headers


# ---------------------------------------------------------------------------
# get_valid_access_token — refresh errors stay server-side
# ---------------------------------------------------------------------------


def _stored_cred(expires_in: timedelta) -> MailboxCredential:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return MailboxCredential(
        id="01HZYJZGXM0KV0K4T8Y9CRED02",
        tenant_id=TEST_TENANT_ID,
        mailbox_id=MAILBOX_ID,
        access_token="stored-access",
        refresh_token="stored-refresh",
        access_token_expires_at=now + expires_in,
        credential_status="active",
    )


def test_valid_token_returned_without_refresh(db: MagicMock) -> None:
    db.scalars.return_value.first.return_value = _stored_cred(timedelta(hours=1))
    with patch(_HTTPX) as httpx_mock:
        token = MailboxService(db).get_valid_access_token(TEST_TENANT_ID, MAILBOX_ID)
    assert token == "stored-access"
    httpx_mock.post.assert_not_called()


def test_no_credential_returns_none(db: MagicMock) -> None:
    with patch(_HTTPX) as httpx_mock:
        assert MailboxService(db).get_valid_access_token(TEST_TENANT_ID, MAILBOX_ID) is None
    httpx_mock.post.assert_not_called()


def test_expiring_token_is_refreshed(db: MagicMock) -> None:
    cred = _stored_cred(timedelta(minutes=2))
    db.scalars.return_value.first.return_value = cred
    with patch(_HTTPX) as httpx_mock:
        httpx_mock.post.return_value = _response(
            200, {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 60}
        )
        token = MailboxService(db).get_valid_access_token(TEST_TENANT_ID, MAILBOX_ID)

    assert token == "new-access"
    assert httpx_mock.post.call_args.kwargs["data"]["refresh_token"] == "stored-refresh"
    assert (cred.access_token, cred.refresh_token) == ("new-access", "new-refresh")
    assert cred.credential_status == "active"
    db.commit.assert_called_once()


def test_refresh_keeps_old_refresh_token_when_not_rotated(db: MagicMock) -> None:
    cred = _stored_cred(timedelta(minutes=-1))
    db.scalars.return_value.first.return_value = cred
    with patch(_HTTPX) as httpx_mock:
        httpx_mock.post.return_value = _response(200, {"access_token": "new-access"})
        MailboxService(db).get_valid_access_token(TEST_TENANT_ID, MAILBOX_ID)
    assert cred.refresh_token == "stored-refresh"


@pytest.mark.parametrize(
    ("status", "payload"),
    [(400, None), (401, None), (500, None), (200, {"refresh_token": "r"})],
    ids=["400", "401", "500", "200-without-access-token"],
)
def test_refresh_failure_is_generic_but_recorded(
    db: MagicMock,
    caplog: pytest.LogCaptureFixture,
    status: int,
    payload: dict | None,
) -> None:
    from fastapi import HTTPException

    from mtf.tenant.services.mailbox_service import MAILBOX_TOKEN_REFRESH_FAILED_MESSAGE

    cred = _stored_cred(timedelta(minutes=-1))
    db.scalars.return_value.first.return_value = cred
    with (
        patch(_HTTPX) as httpx_mock,
        caplog.at_level(logging.WARNING, logger="mtf.tenant.services.mailbox_service"),
        pytest.raises(HTTPException) as exc_info,
    ):
        httpx_mock.post.return_value = _response(status, payload, text=MS_SECRET_TEXT)
        MailboxService(db).get_valid_access_token(TEST_TENANT_ID, MAILBOX_ID)

    exc = exc_info.value
    assert exc.status_code == 400
    assert exc.detail == {
        "code": "MAILBOX_TOKEN_BAD_REQUEST",
        "message": MAILBOX_TOKEN_REFRESH_FAILED_MESSAGE,
    }
    assert MS_SECRET_TEXT not in str(exc.detail)
    # Operators can still see what Microsoft said.
    assert cred.credential_status == "error"
    assert cred.last_error == MS_SECRET_TEXT
    assert cred.last_error_at is not None
    assert MS_SECRET_TEXT in caplog.text
    assert cred.access_token == "stored-access"  # not overwritten on failure
    db.commit.assert_called_once()
