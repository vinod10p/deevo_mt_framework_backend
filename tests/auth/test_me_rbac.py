"""GET /api/auth/me exposes resolver grants for the UI, not the JWT."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from main import app
from mtf.auth.api.session import get_user_service
from mtf.auth.schemas.session import TokenResponse
from mtf.auth.schemas.user import MeReportGrantRead
from mtf.auth.services.me import me_rbac_fields
from mtf.auth.services.permission_resolver import ReportGrant
from mtf.shared.deps import CurrentUser, get_current_user, get_permission_resolver
from tests.auth.test_system_auth_api import _minimal_user
from tests.rpt.conftest import SYSTEM_REPORT_ID
from tests.tenant.conftest import TEST_SYSTEM_USER_ID, TEST_TENANT_ID, TEST_USER_ID


def _resolver(
    *,
    codes: frozenset[str] | None = None,
    grants: dict[str, ReportGrant] | None = None,
) -> MagicMock:
    resolver = MagicMock()
    resolver.permission_codes.return_value = codes or frozenset()
    resolver.report_grants.return_value = grants or {}
    return resolver


def test_me_rbac_fields_sorts_codes_and_maps_report_keys() -> None:
    db = MagicMock()
    db.execute.return_value.all.return_value = [
        (SYSTEM_REPORT_ID, "tenant_account_list"),
    ]
    resolver = _resolver(
        codes=frozenset({"screen.lead.update", "screen.lead.view"}),
        grants={
            SYSTEM_REPORT_ID: ReportGrant(
                report_id=SYSTEM_REPORT_ID,
                can_view=True,
                can_export=True,
            ),
            "01HIDDEN000000000000000001": ReportGrant(
                report_id="01HIDDEN000000000000000001",
                can_view=False,
                can_export=False,
            ),
        },
    )
    user = CurrentUser(
        user_id=TEST_USER_ID,
        user_type="app_user",
        user_scope="tenant",
        tenant_id=TEST_TENANT_ID,
    )
    permissions, reports = me_rbac_fields(db, resolver, user)
    assert permissions == ["screen.lead.update", "screen.lead.view"]
    assert reports == [
        MeReportGrantRead(
            report_key="tenant_account_list",
            can_view=True,
            can_export=True,
        )
    ]


def test_me_rbac_fields_skips_report_query_when_no_viewable_grants() -> None:
    db = MagicMock()
    resolver = _resolver()
    user = CurrentUser(
        user_id=TEST_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    permissions, reports = me_rbac_fields(db, resolver, user)
    assert permissions == []
    assert reports == []
    db.execute.assert_not_called()


def test_token_response_does_not_carry_grants() -> None:
    assert "permissions" not in TokenResponse.model_fields
    assert "reports" not in TokenResponse.model_fields


def test_me_returns_permissions_and_reports() -> None:
    user = _minimal_user()
    user_svc = MagicMock()
    user_svc.get_user.return_value = user
    resolver = _resolver(
        codes=frozenset({"api.system.role.update"}),
        grants={},
    )
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=TEST_SYSTEM_USER_ID,
        user_type="app_user",
        user_scope="system",
        tenant_id=None,
    )
    app.dependency_overrides[get_user_service] = lambda: user_svc
    app.dependency_overrides[get_permission_resolver] = lambda: resolver

    r = TestClient(app).get("/api/auth/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["permissions"] == ["api.system.role.update"]
    assert body["reports"] == []
    resolver.permission_codes.assert_called_once()
    resolver.report_grants.assert_called_once()
