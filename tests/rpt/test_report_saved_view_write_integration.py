"""Saved view write endpoints — integration (live SQL Server + rpt sample reports).

Creates views through the API on ``tenant_account_list`` as a tenant owner/admin and a
member, then hard-deletes every view it created (and their audit rows) afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError

from main import app
from mtf.audit.models import AuditLog
from mtf.auth.models.tenant_user import TenantUser
from mtf.rpt.models import ReportDefinition, ReportSavedView
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.shared.security import generate_id

pytestmark = pytest.mark.integration

REPORT_KEY = "tenant_account_list"
VIEWS_URL = f"/api/reports/{REPORT_KEY}/views"
DEFAULT_URL = f"{VIEWS_URL}/default"


@pytest.fixture(scope="module")
def ctx() -> Generator[dict[str, str], None, None]:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
    try:
        with SessionLocal() as db:
            report = db.scalars(
                select(ReportDefinition).where(
                    ReportDefinition.report_key == REPORT_KEY,
                    ReportDefinition.scope_type == "system",
                    ReportDefinition.is_deleted == False,  # noqa: E712
                )
            ).first()
            members = db.scalars(
                select(TenantUser).where(
                    TenantUser.is_deleted == False, TenantUser.is_active == True  # noqa: E712
                )
            ).all()
            existing = db.scalars(
                select(ReportSavedView.id).where(ReportSavedView.is_deleted == False)  # noqa: E712
            ).all()
    except DBAPIError as exc:
        pytest.skip(f"database not available: {exc.__class__.__name__}")

    by_tenant: dict[str, dict[str, list[str]]] = {}
    for m in members:
        by_tenant.setdefault(m.tenant_id, {}).setdefault(m.role, []).append(m.user_id)
    candidates = [
        (tenant, roles) for tenant, roles in by_tenant.items()
        if (roles.get("owner") or roles.get("admin")) and roles.get("member")
    ]
    if report is None or not candidates:
        pytest.skip("need tenant_account_list and a tenant with an owner/admin and a member")
    if existing:
        pytest.skip("rpt.report_saved_view already has live rows; default tests need a clean tier")
    tenant_id, roles = candidates[0]

    try:
        yield {
            "tenant_id": tenant_id,
            "owner_id": (roles.get("owner") or roles["admin"])[0],
            "member_id": roles["member"][0],
            "report_id": report.id,
            "tag": generate_id()[-8:],
        }
    finally:
        with SessionLocal() as db:
            ids = db.scalars(
                select(ReportSavedView.id).where(
                    ReportSavedView.report_id == report.id,
                    ReportSavedView.view_name.like("pytest write %"),
                )
            ).all()
            if ids:
                db.execute(
                    delete(AuditLog).where(
                        AuditLog.schema_name == "rpt", AuditLog.record_id.in_(ids)
                    )
                )
                db.execute(delete(ReportSavedView).where(ReportSavedView.id.in_(ids)))
            db.commit()


def _as(ctx: dict[str, str], role: str) -> TestClient:
    """Client authenticated as ``role``; identity rides on a header because
    ``app.dependency_overrides`` is global and would leak between clients."""

    def current_user(request: Request) -> CurrentUser:
        return CurrentUser(
            user_id=request.headers["x-test-user-id"], user_type="app_user",
            user_scope="tenant", tenant_id=ctx["tenant_id"],
        )

    app.dependency_overrides[get_current_user] = current_user
    return TestClient(app, headers={"x-test-user-id": ctx[f"{role}_id"]})


def _name(ctx: dict[str, str], label: str) -> str:
    return f"pytest write {ctx['tag']} {label}"


def _create(client: TestClient, ctx: dict[str, str], label: str, **body: object) -> dict:
    payload = {"view_name": _name(ctx, label), "scope_type": "user", **body}
    r = client.post(VIEWS_URL, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _audit_actions(record_id: str) -> list[str]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditLog.action)
                .where(AuditLog.schema_name == "rpt", AuditLog.record_id == record_id)
                .order_by(AuditLog.created_at, AuditLog.id)
            ).all()
        )


def test_create_returns_view_and_writes_audit(ctx: dict[str, str]) -> None:
    owner = _as(ctx, "owner")
    view = _create(
        owner, ctx, "create",
        criteria={"account_type": ["customer"], "status": "",
                  "created_date": {"from": "2026-01-01"}},
        layout={"sort": [{"column_name": "name", "direction": "desc"}]},
    )

    assert view["scope_type"] == "user" and view["can_edit"] is True
    assert view["criteria"] == {"account_type": ["customer"],
                                "created_date": {"from": "2026-01-01"}}
    assert view["layout"]["sort"] == [{"column_name": "name", "direction": "desc"}]
    assert isinstance(view["row_version"], str)
    listed = [v["id"] for v in owner.get(VIEWS_URL).json()]
    assert view["id"] in listed
    assert _audit_actions(view["id"]) == ["insert"]

    with SessionLocal() as db:
        row = db.get(ReportSavedView, view["id"])
        assert row is not None
        assert row.tenant_id == ctx["tenant_id"] and row.user_id == ctx["owner_id"]
        assert row.criteria_json.startswith('{"version":1')


def test_role_rules_on_create(ctx: dict[str, str]) -> None:
    member = _as(ctx, "member")
    r = member.post(VIEWS_URL, json={"view_name": _name(ctx, "m-tenant"), "scope_type": "tenant"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "AUTH_FORBIDDEN"
    r = member.post(VIEWS_URL, json={"view_name": _name(ctx, "m-sys"), "scope_type": "system"})
    assert r.status_code == 403

    _create(member, ctx, "m-user")
    tenant_view = _create(_as(ctx, "owner"), ctx, "o-tenant", scope_type="tenant")
    assert tenant_view["scope_type"] == "tenant"


def test_validation_errors(ctx: dict[str, str]) -> None:
    owner = _as(ctx, "owner")
    r = owner.post(VIEWS_URL, json={"view_name": _name(ctx, "bad-c"), "scope_type": "user",
                                    "criteria": {"status": ["active"], "nope": 1}})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "REPORT_CRITERIA_INVALID"
    assert set(r.json()["detail"]["fields"]) == {"status", "nope"}

    r = owner.post(VIEWS_URL, json={"view_name": _name(ctx, "bad-l"), "scope_type": "user",
                                    "layout": {"group": ["name", "no_such_column"]}})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "REPORT_LAYOUT_INVALID"


def test_duplicate_name_in_tier_is_conflict_but_other_tier_is_fine(ctx: dict[str, str]) -> None:
    owner = _as(ctx, "owner")
    _create(owner, ctx, "dup")
    r = owner.post(VIEWS_URL, json={"view_name": _name(ctx, "dup"), "scope_type": "user"})
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "REPORT_VIEW_CONFLICT", "message": "A saved view with this name already exists"
    }
    _create(owner, ctx, "dup", scope_type="tenant")
    _create(_as(ctx, "member"), ctx, "dup")


def test_new_default_clears_previous_default_in_tier(ctx: dict[str, str]) -> None:
    owner = _as(ctx, "owner")
    first = _create(owner, ctx, "default-1", is_default=True)
    second = _create(owner, ctx, "default-2", is_default=True)

    by_id = {v["id"]: v for v in owner.get(VIEWS_URL).json()}
    assert by_id[first["id"]]["is_default"] is False
    assert by_id[second["id"]]["is_default"] is True
    assert owner.get(DEFAULT_URL).json()["id"] == second["id"]
    assert _audit_actions(first["id"]) == ["insert", "update"]

    patched = owner.patch(
        f"{VIEWS_URL}/{first['id']}",
        json={"row_version": by_id[first["id"]]["row_version"], "is_default": True},
    )
    assert patched.status_code == 200, patched.text
    assert owner.get(DEFAULT_URL).json()["id"] == first["id"]

    member_default = _create(_as(ctx, "member"), ctx, "m-default", is_default=True)
    assert _as(ctx, "member").get(DEFAULT_URL).json()["id"] == member_default["id"]
    assert owner.get(DEFAULT_URL).json()["id"] == first["id"]


def test_patch_row_version_and_fields(ctx: dict[str, str]) -> None:
    owner = _as(ctx, "owner")
    view = _create(owner, ctx, "patch", criteria={"status": "active"})
    url = f"{VIEWS_URL}/{view['id']}"

    r = owner.patch(url, json={"row_version": view["row_version"],
                               "view_name": _name(ctx, "patched"), "criteria": {}})
    assert r.status_code == 200, r.text
    patched = r.json()
    assert patched["view_name"] == _name(ctx, "patched") and patched["criteria"] == {}
    assert patched["row_version"] != view["row_version"]

    stale = owner.patch(url, json={"row_version": view["row_version"], "view_name": "x"})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "REPORT_VIEW_CONFLICT"

    r = owner.patch(url, json={"row_version": patched["row_version"], "scope_type": "tenant"})
    assert r.status_code == 422
    assert _audit_actions(view["id"]) == ["insert", "update"]


def test_patch_and_delete_visibility_and_roles(ctx: dict[str, str]) -> None:
    owner, member = _as(ctx, "owner"), _as(ctx, "member")
    owners_view = _create(owner, ctx, "private")
    tenant_view = _create(owner, ctx, "shared", scope_type="tenant")

    r = member.patch(f"{VIEWS_URL}/{owners_view['id']}",
                     json={"row_version": owners_view["row_version"], "view_name": "x"})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "REPORT_VIEW_NOT_FOUND"
    assert member.delete(f"{VIEWS_URL}/{owners_view['id']}").status_code == 404

    r = member.patch(f"{VIEWS_URL}/{tenant_view['id']}",
                     json={"row_version": tenant_view["row_version"], "view_name": "x"})
    assert r.status_code == 403
    assert member.delete(f"{VIEWS_URL}/{tenant_view['id']}").status_code == 403


def test_delete_soft_deletes_default_without_promoting(ctx: dict[str, str]) -> None:
    member = _as(ctx, "member")
    view = _create(member, ctx, "to-delete", is_default=True)
    url = f"{VIEWS_URL}/{view['id']}"

    r = member.delete(url)
    assert r.status_code == 204 and r.content == b""
    assert view["id"] not in [v["id"] for v in member.get(VIEWS_URL).json()]
    assert member.delete(url).status_code == 404
    assert _audit_actions(view["id"]) == ["insert", "delete"]

    with SessionLocal() as db:
        row = db.get(ReportSavedView, view["id"])
        assert row is not None
        assert (row.is_deleted, row.is_default, row.deleted_by) == (True, False, ctx["member_id"])

    replacement = _create(member, ctx, "to-delete")
    assert replacement["id"] != view["id"]
