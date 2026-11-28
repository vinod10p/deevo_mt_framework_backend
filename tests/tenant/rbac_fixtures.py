"""Shared helpers for tenant RBAC live tests."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_report import RoleReport
from mtf.auth.models.user_role import UserRole
from mtf.rpt.models import ReportDefinition
from mtf.shared.database import SessionLocal
from mtf.tenant.business_units import root_unit_id
from tests.cleanup import SEEDED_SYSTEM_USER_ID

#: Everything the thin ``tenant_admin`` template grants (rbac_fix_05). Members get no
#: template at all — only the roles assigned to them.
THIN_ADMIN_PERMISSIONS = frozenset(
    {"api.auth.role.update", "menu.admin_users.view", "menu.admin_portal_accounts.view"}
)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_member(
    client: TestClient, headers: dict[str, str], *, role: str = "member"
) -> tuple[str, str]:
    email = f"{unique('dmr')}@example.com"
    r = client.post(
        "/api/tenant/users",
        headers=headers,
        json={
            "email": email,
            "password": "MemberSecret123!",
            "role": role,
            "first_name": "Test",
            "last_name": "Member",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["user_id"], email


def custom_role(client: TestClient, headers: dict[str, str], name: str, codes: list[str]) -> dict:
    r = client.post(
        "/api/tenant/roles",
        headers=headers,
        json={"code": f"{name}_{uuid.uuid4().hex[:8]}", "name": name.title()},
    )
    assert r.status_code == 201, r.text
    role = r.json()
    with SessionLocal() as db:
        ids = db.scalars(
            select(Permission.id).where(
                Permission.code.in_(codes),
                Permission.user_scope == "tenant",
                Permission.is_deleted == False,  # noqa: E712
            )
        ).all()
    assert len(ids) == len(codes)
    for pid in ids:
        g = client.post(
            f"/api/tenant/roles/{role['id']}/permissions",
            headers=headers,
            json={"permission_id": pid},
        )
        assert g.status_code == 201, g.text
    return role


def assign_role(client: TestClient, headers: dict[str, str], user_id: str, role_id: str) -> None:
    r = client.post(
        f"/api/tenant/users/{user_id}/roles", headers=headers, json={"role_id": role_id}
    )
    assert r.status_code == 201, r.text


@contextmanager
def report_access(tenant_id: str, report_key: str, *user_ids: str) -> Iterator[str]:
    """Grant the system report ``report_key`` to ``user_ids`` through a throwaway role.

    Admins and members see no reports by default (rbac_fix_05), so report tests grant one.
    Yields the report id; the role and its rows are hard-deleted afterwards.
    """
    by = SEEDED_SYSTEM_USER_ID
    with SessionLocal() as db:
        report_id = db.scalars(
            select(ReportDefinition.id).where(
                ReportDefinition.report_key == report_key,
                ReportDefinition.scope_type == "system",
                ReportDefinition.is_deleted == False,  # noqa: E712
            )
        ).one()
        place = {"tenant_id": tenant_id, "business_unit_id": root_unit_id(db, tenant_id)}
        role = Role.new(
            by=by, **place, code=f"pytest_rpt_{uuid.uuid4().hex[:10]}",
            name="Pytest report reader", user_scope="tenant",
        )
        role_id = role.id  # kept: the commit below expires ``role``
        db.add(role)
        db.flush()  # no ORM relationship orders the role before the rows that use it
        db.add(RoleReport.new(by=by, **place, role_id=role_id, report_id=report_id))
        db.add_all(
            UserRole.new(by=by, **place, user_id=user_id, role_id=role_id, user_scope="tenant")
            for user_id in user_ids
        )
        db.commit()
    try:
        yield report_id
    finally:
        with SessionLocal() as db:
            for model in (UserRole, RoleReport):
                db.execute(delete(model).where(model.role_id == role_id))
            db.execute(delete(Role).where(Role.id == role_id))
            db.commit()
