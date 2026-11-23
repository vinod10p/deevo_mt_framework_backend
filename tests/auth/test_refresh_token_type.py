"""``SessionService.refresh`` only accepts refresh tokens (finding #6, no database)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from mtf.auth.schemas.session import RefreshRequest
from mtf.auth.services.session_service import SessionService
from mtf.shared import security

USER_ID = "01JUSER0000000000000000001"
SESSION_ID = "01JSESS0000000000000000001"


def _service_with_matching_session() -> tuple[SessionService, MagicMock]:
    """Worst case: the hash lookup *does* return a live session for whatever is sent."""
    db = MagicMock()
    session = MagicMock()
    session.id = SESSION_ID
    session.user_id = USER_ID
    session.tenant_id = None
    session.refresh_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        days=1
    )
    user = MagicMock(user_scope="system", first_name="A", last_name="B")
    service = SessionService(db)
    patch.object(service, "_get_session_by_refresh_hash", return_value=session).start()
    patch.object(service, "_get_active_user_by_id", return_value=user).start()
    patch.object(service, "_tenant_name", return_value=None).start()
    return service, db


@pytest.fixture(autouse=True)
def _stop_patches():
    yield
    patch.stopall()


def test_access_token_rejected_by_refresh() -> None:
    service, db = _service_with_matching_session()
    access = security.create_access_token(
        USER_ID, "app_user", "system", None, session_id=SESSION_ID
    )
    with pytest.raises(HTTPException) as exc_info:
        service.refresh(RefreshRequest(refresh_token=access))
    assert exc_info.value.status_code == 401
    db.commit.assert_not_called()  # session not rotated


def test_refresh_token_accepted_and_new_pair_is_typed() -> None:
    service, db = _service_with_matching_session()
    refresh = security.create_refresh_token(USER_ID, SESSION_ID)
    out = service.refresh(RefreshRequest(refresh_token=refresh))

    assert security.decode_access_token(out.access_token)["sid"] == SESSION_ID
    assert security.decode_refresh_token(out.refresh_token)["typ"] == "refresh"
    db.commit.assert_called_once()
