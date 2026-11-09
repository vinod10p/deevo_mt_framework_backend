"""Pydantic schemas — auth domain."""

from mtf.auth.schemas.default_role_report import (
    DefaultRoleReportCreate,
    DefaultRoleReportRead,
    DefaultRoleReportUpdate,
)
from mtf.auth.schemas.permission import (
    PermissionAction,
    PermissionCreate,
    PermissionRead,
    PermissionResourceType,
    PermissionUpdate,
)
from mtf.auth.schemas.role import RoleCreate, RoleRead, RoleUpdate, TenantRoleCreate
from mtf.auth.schemas.role_permission import RolePermissionCreate, RolePermissionRead
from mtf.auth.schemas.role_report import RoleReportCreate, RoleReportRead, RoleReportUpdate
from mtf.auth.schemas.session import LoginRequest, LogoutRequest, RefreshRequest, TokenResponse
from mtf.auth.schemas.tenant_user import (
    TenantMembershipCreate,
    TenantMembershipRead,
    TenantMembershipUpdate,
    TenantUserCreate,
    TenantUserRead,
    TenantUserRole,
    TenantUserUpdate,
)
from mtf.auth.schemas.user import (
    MeReportGrantRead,
    UserCreate,
    UserMeRead,
    UserRead,
    UserScope,
    UserUpdate,
)
from mtf.auth.schemas.user_role import UserRoleCreate, UserRoleRead

__all__ = [
    "DefaultRoleReportCreate",
    "DefaultRoleReportRead",
    "DefaultRoleReportUpdate",
    "LoginRequest",
    "LogoutRequest",
    "PermissionAction",
    "PermissionCreate",
    "PermissionRead",
    "PermissionResourceType",
    "PermissionUpdate",
    "RefreshRequest",
    "RoleCreate",
    "RolePermissionCreate",
    "RolePermissionRead",
    "RoleRead",
    "RoleReportCreate",
    "RoleReportRead",
    "RoleReportUpdate",
    "RoleUpdate",
    "TenantRoleCreate",
    "UserRoleCreate",
    "UserRoleRead",
    "TokenResponse",
    "TenantUserCreate",
    "TenantUserRead",
    "TenantUserRole",
    "TenantUserUpdate",
    "TenantMembershipCreate",
    "TenantMembershipRead",
    "TenantMembershipUpdate",
    "MeReportGrantRead",
    "UserCreate",
    "UserMeRead",
    "UserRead",
    "UserScope",
    "UserUpdate",
]
