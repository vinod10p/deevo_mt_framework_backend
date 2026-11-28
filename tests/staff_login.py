"""Log in as tenant staff through the real ``/api/auth/login`` route (live tests)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from mtf.tenant.business_units import FIRST_STORE_CODE

#: Password given to the staff users the live tests create.
PASSWORD = "Secret123!"


def login_staff(
    client: TestClient,
    email: str,
    tenant_id: str,
    *,
    password: str = PASSWORD,
    store: str = FIRST_STORE_CODE,
) -> dict:
    """Log in at ``store`` and return the token response.

    The default store, MAIN, is open to every new staff member: admins through their root
    role, members as their default store.
    """
    r = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
            "tenant_id": tenant_id,
            "business_unit_code": store,
            "created_from": "web",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == tenant_id
    return body


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def staff_headers(client: TestClient, email: str, tenant_id: str, **login: str) -> dict[str, str]:
    """Log in (see :func:`login_staff`) and return the ``Authorization`` header."""
    return bearer(login_staff(client, email, tenant_id, **login)["access_token"])
