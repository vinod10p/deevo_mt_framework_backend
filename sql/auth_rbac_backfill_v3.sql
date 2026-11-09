/*
auth_rbac_backfill_v3.sql
Idempotent backfill / "apply defaults to all tenants" for RBAC v3.

Run AFTER auth_rbac_seed_v3.sql. Safe to re-run: inserts only missing
role_report and user_role rows. Fails if a platform template role is
missing or a live membership.role cannot be mapped.

Dual-write map (membership.role → platform auth.role.code):
  tenant_user.owner|admin  → tenant_admin
  tenant_user.member|viewer → tenant_member
  tenant_account_user.admin  → account_admin
  tenant_account_user.member → account_member

New row ids are deterministic (prefix 01JRACBKF + SHA-256 hex) so a
retry never invents a second primary key for the same natural key.
*/

USE [deevo_app_dev2];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF NOT EXISTS (SELECT 1 FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_admin' AND is_deleted = 0)
    THROW 50010, 'RBAC backfill: platform role tenant_admin is missing. Run auth_rbac_seed_v3.sql first.', 1;
IF NOT EXISTS (SELECT 1 FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_member' AND is_deleted = 0)
    THROW 50010, 'RBAC backfill: platform role tenant_member is missing. Run auth_rbac_seed_v3.sql first.', 1;
IF NOT EXISTS (SELECT 1 FROM auth.role WHERE tenant_id IS NULL AND code = 'account_admin' AND is_deleted = 0)
    THROW 50010, 'RBAC backfill: platform role account_admin is missing. Run auth_rbac_seed_v3.sql first.', 1;
IF NOT EXISTS (SELECT 1 FROM auth.role WHERE tenant_id IS NULL AND code = 'account_member' AND is_deleted = 0)
    THROW 50010, 'RBAC backfill: platform role account_member is missing. Run auth_rbac_seed_v3.sql first.', 1;

IF EXISTS (
    SELECT 1
    FROM auth.tenant_user tu
    JOIN tenant.tenant t ON t.id = tu.tenant_id AND t.is_deleted = 0
    WHERE tu.is_deleted = 0
      AND tu.role NOT IN ('owner', 'admin', 'member', 'viewer')
)
    THROW 50011, 'RBAC backfill: tenant_user.role is not owner|admin|member|viewer.', 1;

IF EXISTS (
    SELECT 1
    FROM auth.tenant_account_user tau
    JOIN tenant.tenant t ON t.id = tau.tenant_id AND t.is_deleted = 0
    WHERE tau.is_deleted = 0
      AND tau.role NOT IN ('admin', 'member')
)
    THROW 50011, 'RBAC backfill: tenant_account_user.role is not admin|member.', 1;

IF EXISTS (
    SELECT 1
    FROM auth.tenant_user tu
    JOIN auth.app_user u ON u.id = tu.user_id
    JOIN tenant.tenant t ON t.id = tu.tenant_id AND t.is_deleted = 0
    WHERE tu.is_deleted = 0
      AND u.user_scope <> 'tenant'
)
    THROW 50012, 'RBAC backfill: tenant_user is linked to a non-tenant app_user.', 1;

IF EXISTS (
    SELECT 1
    FROM auth.tenant_account_user tau
    JOIN auth.app_user u ON u.id = tau.user_id
    JOIN tenant.tenant t ON t.id = tau.tenant_id AND t.is_deleted = 0
    WHERE tau.is_deleted = 0
      AND u.user_scope <> 'tenant_account'
)
    THROW 50012, 'RBAC backfill: tenant_account_user is linked to a non-portal app_user.', 1;

/* -------------------------------------------------------------------------
   1. Copy default_role_report → role_report for every live tenant
   ------------------------------------------------------------------------- */
INSERT INTO auth.role_report (id, tenant_id, role_id, report_id, can_view, can_export)
SELECT
    LEFT('01JRACBKF' + CONVERT(varchar(64), HASHBYTES(
        'SHA2_256', CONCAT(N'rr|', t.id, N'|', d.role_id, N'|', d.report_id)), 2), 26),
    t.id,
    d.role_id,
    d.report_id,
    d.can_view,
    d.can_export
FROM tenant.tenant AS t
JOIN auth.default_role_report AS d
    ON d.is_deleted = 0
   AND d.is_active = 1
WHERE t.is_deleted = 0
  AND NOT EXISTS (
        SELECT 1
        FROM auth.role_report AS rr
        WHERE rr.tenant_id = t.id
          AND rr.role_id = d.role_id
          AND rr.report_id = d.report_id
          AND rr.is_deleted = 0
    );

/* -------------------------------------------------------------------------
   2. tenant_user.role → user_role
   ------------------------------------------------------------------------- */
INSERT INTO auth.user_role (id, tenant_id, user_id, account_id, role_id, user_scope)
SELECT
    LEFT('01JRACBKF' + CONVERT(varchar(64), HASHBYTES(
        'SHA2_256', CONCAT(N'ur|', tu.tenant_id, N'|', tu.user_id, N'|', r.id)), 2), 26),
    tu.tenant_id,
    tu.user_id,
    NULL,
    r.id,
    'tenant'
FROM auth.tenant_user AS tu
JOIN tenant.tenant AS t
    ON t.id = tu.tenant_id
   AND t.is_deleted = 0
JOIN auth.app_user AS u
    ON u.id = tu.user_id
   AND u.user_scope = 'tenant'
JOIN auth.role AS r
    ON r.tenant_id IS NULL
   AND r.is_deleted = 0
   AND r.code = CASE tu.role
                    WHEN 'owner'  THEN 'tenant_admin'
                    WHEN 'admin'  THEN 'tenant_admin'
                    WHEN 'member' THEN 'tenant_member'
                    WHEN 'viewer' THEN 'tenant_member'
                END
WHERE tu.is_deleted = 0
  AND NOT EXISTS (
        SELECT 1
        FROM auth.user_role AS ur
        WHERE ur.tenant_id = tu.tenant_id
          AND ur.user_id = tu.user_id
          AND ur.account_id IS NULL
          AND ur.role_id = r.id
          AND ur.is_deleted = 0
    );

/* -------------------------------------------------------------------------
   3. tenant_account_user.role → user_role
   ------------------------------------------------------------------------- */
INSERT INTO auth.user_role (id, tenant_id, user_id, account_id, role_id, user_scope)
SELECT
    LEFT('01JRACBKF' + CONVERT(varchar(64), HASHBYTES(
        'SHA2_256', CONCAT(N'ur|', tau.tenant_id, N'|', tau.user_id, N'|', tau.account_id, N'|', r.id)), 2), 26),
    tau.tenant_id,
    tau.user_id,
    tau.account_id,
    r.id,
    'tenant_account'
FROM auth.tenant_account_user AS tau
JOIN tenant.tenant AS t
    ON t.id = tau.tenant_id
   AND t.is_deleted = 0
JOIN auth.app_user AS u
    ON u.id = tau.user_id
   AND u.user_scope = 'tenant_account'
JOIN auth.role AS r
    ON r.tenant_id IS NULL
   AND r.is_deleted = 0
   AND r.code = CASE tau.role
                    WHEN 'admin'  THEN 'account_admin'
                    WHEN 'member' THEN 'account_member'
                END
WHERE tau.is_deleted = 0
  AND NOT EXISTS (
        SELECT 1
        FROM auth.user_role AS ur
        WHERE ur.tenant_id = tau.tenant_id
          AND ur.user_id = tau.user_id
          AND ur.account_id = tau.account_id
          AND ur.role_id = r.id
          AND ur.is_deleted = 0
    );

COMMIT TRANSACTION;
GO
