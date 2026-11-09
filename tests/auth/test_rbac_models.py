"""ORM mapping tests for RBAC v3 tables — no database.

Asserts table location, columns, composite foreign keys, and the
``UQ_*_id_user_scope`` unique constraints that those FKs need.
"""

from __future__ import annotations

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import configure_mappers

from mtf.auth.models.default_role_report import DefaultRoleReport
from mtf.auth.models.permission import Permission
from mtf.auth.models.role import Role
from mtf.auth.models.role_permission import RolePermission
from mtf.auth.models.role_report import RoleReport
from mtf.auth.models.user import User
from mtf.auth.models.user_role import UserRole

_STANDARD = {
    "id",
    "is_active",
    "is_deleted",
    "row_version",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "deleted_at",
    "deleted_by",
}


@pytest.fixture(scope="module", autouse=True)
def _configure_mappers_for_fk_resolution() -> None:
    from mtf.rpt.models.report_definition import ReportDefinition  # noqa: F401
    from mtf.tenant.models.tenant import Tenant  # noqa: F401
    from mtf.tenant.models.tenant_account import TenantAccount  # noqa: F401

    _ = User.__table__, Tenant.__table__, TenantAccount.__table__, ReportDefinition.__table__
    _ = (
        Permission.__table__,
        Role.__table__,
        RolePermission.__table__,
        UserRole.__table__,
        RoleReport.__table__,
        DefaultRoleReport.__table__,
    )
    configure_mappers()


def _column_names(model: type) -> set[str]:
    return set(model.__mapper__.columns.keys())


def _unique_constraint_names(model: type) -> set[str | None]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _fk_column_pairs(model: type) -> set[tuple[tuple[str, ...], tuple[tuple[str, str], ...]]]:
    pairs: set[tuple[tuple[str, ...], tuple[tuple[str, str], ...]]] = set()
    for constraint in model.__table__.foreign_key_constraints:
        local = tuple(constraint.column_keys)
        remote = tuple(
            (element.column.table.fullname, element.column.key) for element in constraint.elements
        )
        pairs.add((local, remote))
    return pairs


def test_permission_mapping() -> None:
    assert Permission.__table__.schema == "auth"
    assert Permission.__tablename__ == "permission"
    assert _column_names(Permission) == _STANDARD | {
        "code",
        "resource_type",
        "resource_code",
        "action",
        "user_scope",
        "description",
    }
    assert "UQ_permission_id_user_scope" in _unique_constraint_names(Permission)


def test_role_mapping() -> None:
    assert Role.__table__.schema == "auth"
    assert Role.__tablename__ == "role"
    assert _column_names(Role) == _STANDARD | {
        "tenant_id",
        "code",
        "name",
        "description",
        "user_scope",
        "is_system",
    }
    assert "UQ_role_id_user_scope" in _unique_constraint_names(Role)
    assert (("tenant_id",), (("tenant.tenant", "id"),)) in _fk_column_pairs(Role)


def test_app_user_exposes_scope_unique_for_user_role_fk() -> None:
    assert "UQ_app_user_id_user_scope" in _unique_constraint_names(User)


def test_role_permission_composite_foreign_keys() -> None:
    assert RolePermission.__table__.schema == "auth"
    assert RolePermission.__tablename__ == "role_permission"
    assert _column_names(RolePermission) == _STANDARD | {
        "role_id",
        "permission_id",
        "user_scope",
    }
    fks = _fk_column_pairs(RolePermission)
    assert (
        ("role_id", "user_scope"),
        (("auth.role", "id"), ("auth.role", "user_scope")),
    ) in fks
    assert (
        ("permission_id", "user_scope"),
        (("auth.permission", "id"), ("auth.permission", "user_scope")),
    ) in fks


def test_user_role_composite_foreign_keys_and_scope_shape() -> None:
    assert UserRole.__table__.schema == "auth"
    assert UserRole.__tablename__ == "user_role"
    assert _column_names(UserRole) == _STANDARD | {
        "tenant_id",
        "user_id",
        "account_id",
        "role_id",
        "user_scope",
    }
    fks = _fk_column_pairs(UserRole)
    assert (
        ("user_id", "user_scope"),
        (("auth.app_user", "id"), ("auth.app_user", "user_scope")),
    ) in fks
    assert (
        ("role_id", "user_scope"),
        (("auth.role", "id"), ("auth.role", "user_scope")),
    ) in fks
    names = {constraint.name for constraint in UserRole.__table__.constraints}
    assert "CK_user_role_scope_shape" in names


def test_role_report_mapping() -> None:
    assert RoleReport.__table__.schema == "auth"
    assert RoleReport.__tablename__ == "role_report"
    assert _column_names(RoleReport) == _STANDARD | {
        "tenant_id",
        "role_id",
        "report_id",
        "can_view",
        "can_export",
    }
    fks = _fk_column_pairs(RoleReport)
    assert (("tenant_id",), (("tenant.tenant", "id"),)) in fks
    assert (("role_id",), (("auth.role", "id"),)) in fks
    assert (("report_id",), (("rpt.report_definition", "id"),)) in fks


def test_default_role_report_mapping() -> None:
    assert DefaultRoleReport.__table__.schema == "auth"
    assert DefaultRoleReport.__tablename__ == "default_role_report"
    assert _column_names(DefaultRoleReport) == _STANDARD | {
        "role_id",
        "report_id",
        "can_view",
        "can_export",
    }
    fks = _fk_column_pairs(DefaultRoleReport)
    assert (("role_id",), (("auth.role", "id"),)) in fks
    assert (("report_id",), (("rpt.report_definition", "id"),)) in fks


def test_repr_includes_identity() -> None:
    permission = Permission(
        id="01PERM00000000000000000001",
        code="screen.lead.view",
        resource_type="screen",
        resource_code="lead",
        action="view",
        user_scope="tenant",
    )
    assert "screen.lead.view" in repr(permission)
    role = Role(
        id="01ROLE00000000000000000001",
        code="tenant_admin",
        name="Tenant Admin",
        user_scope="tenant",
    )
    assert "tenant_admin" in repr(role)
