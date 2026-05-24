"""TenantService handling of DB unique violations (mocked session)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from mtf.tenant.schemas import TenantCreate, TenantUpdate
from mtf.tenant.services.tenant_service import TenantService

from tests.tenant.conftest import TEST_TENANT_ID, minimal_tenant


def test_create_tenant_duplicate_subdomain_raises_409() -> None:
    db = MagicMock()
    db.add = MagicMock()
    orig = Exception(
        "Cannot insert duplicate key row in object 'tenant.tenant' "
        "with unique index 'UQ_tenant_subdomain'."
    )
    db.commit.side_effect = IntegrityError("stmt", {}, orig)
    db.rollback = MagicMock()

    svc = TenantService(db)
    with pytest.raises(HTTPException) as exc_info:
        svc.create_tenant(TenantCreate(name="Co", subdomain="dup"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "TENANT_SUBDOMAIN_CONFLICT"
    db.rollback.assert_called_once()


def test_create_tenant_non_unique_integrity_error_reraises() -> None:
    db = MagicMock()
    db.add = MagicMock()
    orig = Exception("Some other integrity failure")
    db.commit.side_effect = IntegrityError("stmt", {}, orig)
    db.rollback = MagicMock()

    svc = TenantService(db)
    with pytest.raises(IntegrityError):
        svc.create_tenant(TenantCreate(name="Co", subdomain="x"))

    db.rollback.assert_called_once()


def test_update_tenant_duplicate_subdomain_raises_409() -> None:
    row = minimal_tenant(id=TEST_TENANT_ID)
    db = MagicMock()
    db.scalars.return_value.first.return_value = row
    db.add = MagicMock()
    orig = Exception("Cannot insert duplicate key row")
    db.commit.side_effect = IntegrityError("stmt", {}, orig)
    db.rollback = MagicMock()

    svc = TenantService(db)
    payload = TenantUpdate(row_version=row.row_version, subdomain="taken")

    with pytest.raises(HTTPException) as exc_info:
        svc.update_tenant(TEST_TENANT_ID, payload)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "TENANT_SUBDOMAIN_CONFLICT"
    db.rollback.assert_called_once()
