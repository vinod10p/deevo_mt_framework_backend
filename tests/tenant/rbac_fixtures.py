"""Shared helpers for tenant RBAC live tests."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from mtf.auth.models.permission import Permission
from mtf.shared.database import SessionLocal


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
