"""Saved view read endpoints — integration (live SQL Server + rpt sample reports).

Inserts committed test views on ``tenant_account_list`` (system, tenant, own user view,
another user's view, a deleted view) and hard-deletes them afterwards.
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from main import app
from mtf.auth.models.tenant_user import TenantUser
from mtf.rpt.models import ReportDefinition, ReportSavedView
from mtf.shared.database import SessionLocal
from mtf.shared.deps import CurrentUser, get_current_user
from mtf.shared.security import generate_id

pytestmark = pytest.mark.integration

REPORT_KEY = "tenant_account_list"
LIST_URL = f"/api/reports/{REPORT_KEY}/views"
DEFAULT_URL = f"/api/reports/{REPORT_KEY}/views/default"
EMPTY_LAYOUT = {"version": 1, "columns": [], "sort": [], "group": [], "aggregates": []}


@pytest.fixture(scope="module")
def setup() -> Generator[dict[str, object], None, None]:
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
    tenant_id, roles = candidates[0]
    owner_id = (roles.get("owner") or roles["admin"])[0]
    member_id = roles["member"][0]

    tag = generate_id()[-8:]
    ids = {name: generate_id() for name in ("system", "tenant", "owner", "member", "deleted")}
    rows = [
        ("system", None, None, f"pytest system {tag}"),
        ("tenant", tenant_id, None, f"pytest tenant {tag}"),
        ("owner", tenant_id, owner_id, f"pytest owner {tag}"),
        ("member", tenant_id, member_id, f"pytest member {tag}"),
        ("deleted", tenant_id, owner_id, f"pytest deleted {tag}"),
    ]
    with SessionLocal() as db:
        for key, row_tenant, user_id, name in rows:
            scope = "system" if key == "system" else ("tenant" if key == "tenant" else "user")
            db.add(
                ReportSavedView(
                    id=ids[key],
                    tenant_id=row_tenant,
                    report_id=report.id,
                    scope_type=scope,
                    user_id=user_id,
                    view_name=name,
                    criteria_json=json.dumps({"version": 1, "status": "active"}),
                    layout_json=json.dumps(EMPTY_LAYOUT),
                    is_deleted=key == "deleted",
                )
            )
        db.commit()
    try:
        yield {"tenant_id": tenant_id, "owner_id": owner_id, "member_id": member_id,
               "ids": ids}
    finally:
        with SessionLocal() as db:
            db.execute(delete(ReportSavedView).where(ReportSavedView.id.in_(ids.values())))
            db.commit()


def _as(tenant_id: str, user_id: str) -> TestClient:
    user = CurrentUser(user_id=user_id, user_type="app_user", user_scope="tenant",
                       tenant_id=tenant_id)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _set_defaults(ids: dict[str, str], *keys: str) -> None:
    with SessionLocal() as db:
        db.execute(
            update(ReportSavedView)
            .where(ReportSavedView.id.in_([ids[k] for k in ("system", "tenant", "owner")]))
            .values(is_default=False)
        )
        if keys:
            db.execute(
                update(ReportSavedView)
                .where(ReportSavedView.id.in_([ids[k] for k in keys]))
                .values(is_default=True)
            )
        db.commit()


def _mine(body: list[dict], ids: dict[str, str]) -> list[dict]:
    ours = set(ids.values())
    return [v for v in body if v["id"] in ours]


def test_owner_sees_system_tenant_and_own_views_only(setup: dict) -> None:
    ids = setup["ids"]
    r = _as(setup["tenant_id"], setup["owner_id"]).get(LIST_URL)
    assert r.status_code == 200, r.text
    views = _mine(r.json(), ids)

    assert [v["id"] for v in views] == [ids["owner"], ids["tenant"], ids["system"]]
    assert {v["id"]: v["can_edit"] for v in views} == {
        ids["owner"]: True, ids["tenant"]: True, ids["system"]: False,
    }
    assert views[0]["criteria"] == {"status": "active"}
    assert set(views[0]["layout"]) == {"columns", "sort", "group", "aggregates"}
    assert isinstance(views[0]["row_version"], str)


def test_member_sees_own_view_and_cannot_edit_tenant_view(setup: dict) -> None:
    ids = setup["ids"]
    views = _mine(_as(setup["tenant_id"], setup["member_id"]).get(LIST_URL).json(), ids)

    assert [v["id"] for v in views] == [ids["member"], ids["tenant"], ids["system"]]
    assert {v["id"]: v["can_edit"] for v in views} == {
        ids["member"]: True, ids["tenant"]: False, ids["system"]: False,
    }


def test_other_tenant_cannot_list_views_for_hidden_report(setup: dict) -> None:
    r = _as("01HZYJZGXM0KV0K4T8Y9ABCDE9", setup["owner_id"]).get(LIST_URL)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_NOT_FOUND"


def test_default_resolution_user_then_tenant_then_system(setup: dict) -> None:
    ids = setup["ids"]
    owner = _as(setup["tenant_id"], setup["owner_id"])
    try:
        _set_defaults(ids, "system", "tenant", "owner")
        assert owner.get(DEFAULT_URL).json()["id"] == ids["owner"]

        _set_defaults(ids, "system", "tenant")
        assert owner.get(DEFAULT_URL).json()["id"] == ids["tenant"]

        _set_defaults(ids, "system")
        assert owner.get(DEFAULT_URL).json()["id"] == ids["system"]

        _set_defaults(ids, "system", "tenant", "owner")
        member = _as(setup["tenant_id"], setup["member_id"])
        assert member.get(DEFAULT_URL).json()["id"] == ids["tenant"]
    finally:
        _set_defaults(ids)


def test_default_204_when_no_defaults(setup: dict) -> None:
    _set_defaults(setup["ids"])
    r = _as(setup["tenant_id"], setup["owner_id"]).get(DEFAULT_URL)
    if r.status_code == 200:
        pytest.skip("another saved view on this report is already a default")
    assert r.status_code == 204


def test_unknown_report_404(setup: dict) -> None:
    r = _as(setup["tenant_id"], setup["owner_id"]).get("/api/reports/no_such_report/views")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_NOT_FOUND"
