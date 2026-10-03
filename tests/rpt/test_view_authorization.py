"""ReportViewAuthorizer — saved-view role rules (mocked tenant-role lookup)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from mtf.rpt.services import ReportViewAuthorizer
from tests.rpt.conftest import (
    OTHER_TENANT_ID,
    TEST_TENANT_ID,
    TEST_USER_ID,
    minimal_saved_view,
    portal_user,
    system_user,
    tenant_user,
)

OTHER_USER_ID = "01HZYJZGXM0KV0K4T8Y9ABCDE7"


def _authorizer(role: str | None) -> tuple[ReportViewAuthorizer, MagicMock]:
    db = MagicMock()
    db.scalars.return_value.first.return_value = role
    return ReportViewAuthorizer(db), db


@pytest.mark.parametrize(
    ("user", "role", "allowed"),
    [
        (tenant_user(), "member", True),
        (portal_user(), None, True),
        (tenant_user(tenant_id=None), "owner", False),
        (system_user(), None, False),
    ],
)
def test_manage_user_views(user, role, allowed: bool) -> None:
    authorizer, _ = _authorizer(role)
    assert authorizer.is_allowed(user, "report.view.manage_user") is allowed


@pytest.mark.parametrize(
    ("user", "role", "allowed"),
    [
        (tenant_user(), "owner", True),
        (tenant_user(), "admin", True),
        (tenant_user(), "member", False),
        (tenant_user(), "viewer", False),
        (tenant_user(), None, False),
        (portal_user(), "owner", False),
        (system_user(), "owner", False),
    ],
)
def test_manage_tenant_views(user, role: str | None, allowed: bool) -> None:
    authorizer, _ = _authorizer(role)
    assert authorizer.is_allowed(user, "report.view.manage_tenant") is allowed


@pytest.mark.parametrize("role", ["owner", "admin", None])
def test_system_views_never_manageable(role: str | None) -> None:
    authorizer, _ = _authorizer(role)
    assert authorizer.is_allowed(tenant_user(), "report.view.manage_system") is False


def test_tenant_role_lookup_scoped_to_caller_and_cached() -> None:
    authorizer, db = _authorizer("owner")
    authorizer.is_allowed(tenant_user(), "report.view.manage_tenant")
    authorizer.is_allowed(tenant_user(), "report.view.manage_tenant")
    assert db.scalars.call_count == 1
    params = db.scalars.call_args.args[0].compile().params
    assert TEST_TENANT_ID in params.values()
    assert TEST_USER_ID in params.values()


def test_authorize_raises_auth_forbidden() -> None:
    authorizer, _ = _authorizer("member")
    with pytest.raises(HTTPException) as exc_info:
        authorizer.authorize(tenant_user(), "report.view.manage_tenant")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "AUTH_FORBIDDEN"


@pytest.mark.parametrize(
    ("view_kwargs", "role", "expected"),
    [
        ({"scope_type": "user"}, "member", True),
        ({"scope_type": "user", "user_id": OTHER_USER_ID}, "owner", False),
        ({"scope_type": "user", "tenant_id": OTHER_TENANT_ID}, "member", False),
        ({"scope_type": "tenant", "user_id": None}, "owner", True),
        ({"scope_type": "tenant", "user_id": None}, "member", False),
        ({"scope_type": "tenant", "user_id": None, "tenant_id": OTHER_TENANT_ID}, "owner", False),
        ({"scope_type": "system", "user_id": None, "tenant_id": None}, "owner", False),
    ],
)
def test_can_edit(view_kwargs: dict, role: str, expected: bool) -> None:
    authorizer, _ = _authorizer(role)
    assert authorizer.can_edit(tenant_user(), minimal_saved_view(**view_kwargs)) is expected


def test_authorize_edit() -> None:
    authorizer, _ = _authorizer("member")
    authorizer.authorize_edit(tenant_user(), minimal_saved_view())
    with pytest.raises(HTTPException) as exc_info:
        authorizer.authorize_edit(
            tenant_user(), minimal_saved_view(scope_type="tenant", user_id=None)
        )
    assert exc_info.value.detail["code"] == "AUTH_FORBIDDEN"


def test_portal_user_can_edit_own_view_only() -> None:
    authorizer, _ = _authorizer(None)
    assert authorizer.can_edit(portal_user(), minimal_saved_view()) is True
    tenant_view = minimal_saved_view(scope_type="tenant", user_id=None)
    assert authorizer.can_edit(portal_user(), tenant_view) is False
