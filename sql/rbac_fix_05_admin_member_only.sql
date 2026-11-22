/*
    rbac_fix_05_admin_member_only.sql
    Database: deevo_app_dev2
    Requires: auth.tenant_user, auth.role, auth.role_permission, auth.user_role,
              auth.default_role_report, auth.role_report,
              rbac_fix_04_default_member_role.sql (column may exist)

    Membership is admin | member only.
      admin  → automatic thin tenant_admin (Users, Portal Accounts, Role Admin)
      member → no automatic template role; only assigned roles grant access

    1. owner → admin, viewer → member
    2. CK_tenant_user_role → admin | member
    3. Soft-delete every live grant on tenant_admin except:
         api.auth.role.update
         menu.admin_users.view
         menu.admin_portal_accounts.view
       Soft-delete every live grant on tenant_member
    4. Soft-delete default_role_report and live role_report for both templates
    5. Soft-delete every live tenant_member user_role (members hold no template)
    6. Ensure every live admin has tenant_admin; remove tenant_member from admins
    7. lg tenant: keep a@lg.com as admin; soft-delete other lg staff memberships
    8. New members default the unused flag off when the column exists

    Apply as deevo. Safe to rerun.
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

USE [deevo_app_dev2];
GO

BEGIN TRANSACTION;

DECLARE @system varchar(26) = '01HYSTEM00000000000000000';
DECLARE @now datetime2(3) = SYSUTCDATETIME();

DECLARE @R_TENANT_ADMIN varchar(26) = (
    SELECT id FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_admin' AND is_deleted = 0
);
DECLARE @R_TENANT_MEMBER varchar(26) = (
    SELECT id FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_member' AND is_deleted = 0
);
IF @R_TENANT_ADMIN IS NULL OR @R_TENANT_MEMBER IS NULL
    THROW 51050, N'Platform tenant_admin / tenant_member missing.', 1;

/* -------------------------------------------------------------------------
   1. Collapse membership strings
   ------------------------------------------------------------------------- */
UPDATE auth.tenant_user
SET role = 'admin', updated_at = @now
WHERE is_deleted = 0 AND role = 'owner';

UPDATE auth.tenant_user
SET role = 'member', updated_at = @now
WHERE is_deleted = 0 AND role = 'viewer';

/* -------------------------------------------------------------------------
   2. Check constraint
   ------------------------------------------------------------------------- */
IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_tenant_user_role'
      AND parent_object_id = OBJECT_ID('auth.tenant_user')
)
    ALTER TABLE auth.tenant_user DROP CONSTRAINT CK_tenant_user_role;

ALTER TABLE auth.tenant_user WITH CHECK
    ADD CONSTRAINT CK_tenant_user_role CHECK ([role] IN ('admin', 'member'));

/* -------------------------------------------------------------------------
   3. Thin tenant_admin; empty tenant_member
   ------------------------------------------------------------------------- */
DECLARE @KeepAdmin TABLE (code varchar(150) NOT NULL PRIMARY KEY);
INSERT INTO @KeepAdmin (code) VALUES
    ('api.auth.role.update'),
    ('menu.admin_users.view'),
    ('menu.admin_portal_accounts.view');

UPDATE rp
SET is_active = 0,
    is_deleted = 1,
    deleted_at = @now,
    deleted_by = @system,
    updated_at = @now,
    updated_by = @system
FROM auth.role_permission AS rp
JOIN auth.permission AS p ON p.id = rp.permission_id
WHERE rp.is_deleted = 0
  AND rp.role_id = @R_TENANT_ADMIN
  AND p.code NOT IN (SELECT code FROM @KeepAdmin);

UPDATE auth.role_permission
SET is_active = 0,
    is_deleted = 1,
    deleted_at = @now,
    deleted_by = @system,
    updated_at = @now,
    updated_by = @system
WHERE is_deleted = 0
  AND role_id = @R_TENANT_MEMBER;

/* Ensure the three admin grants exist (idempotent). */
DECLARE @P_ROLE varchar(26) = (
    SELECT id FROM auth.permission WHERE user_scope = 'tenant' AND code = 'api.auth.role.update' AND is_deleted = 0
);
DECLARE @P_USERS varchar(26) = (
    SELECT id FROM auth.permission WHERE user_scope = 'tenant' AND code = 'menu.admin_users.view' AND is_deleted = 0
);
DECLARE @P_PORTAL varchar(26) = (
    SELECT id FROM auth.permission WHERE user_scope = 'tenant' AND code = 'menu.admin_portal_accounts.view' AND is_deleted = 0
);
IF @P_ROLE IS NULL OR @P_USERS IS NULL OR @P_PORTAL IS NULL
    THROW 51051, N'Admin bundle permissions missing. Apply catalog / nav_menu_fix_01 first.', 1;

IF NOT EXISTS (
    SELECT 1 FROM auth.role_permission
    WHERE role_id = @R_TENANT_ADMIN AND permission_id = @P_ROLE AND is_deleted = 0
)
    INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
    VALUES ('01JRACMTFGA000000000000013', @R_TENANT_ADMIN, @P_ROLE, 'tenant');

IF NOT EXISTS (
    SELECT 1 FROM auth.role_permission
    WHERE role_id = @R_TENANT_ADMIN AND permission_id = @P_USERS AND is_deleted = 0
)
    INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
    VALUES ('01JRACNAVGA000000000000002', @R_TENANT_ADMIN, @P_USERS, 'tenant');

IF NOT EXISTS (
    SELECT 1 FROM auth.role_permission
    WHERE role_id = @R_TENANT_ADMIN AND permission_id = @P_PORTAL AND is_deleted = 0
)
    INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
    VALUES ('01JRACNAVGA000000000000003', @R_TENANT_ADMIN, @P_PORTAL, 'tenant');

/* -------------------------------------------------------------------------
   4. No template report grants
   ------------------------------------------------------------------------- */
UPDATE auth.default_role_report
SET is_active = 0,
    is_deleted = 1,
    deleted_at = @now,
    deleted_by = @system,
    updated_at = @now,
    updated_by = @system
WHERE is_deleted = 0
  AND role_id IN (@R_TENANT_ADMIN, @R_TENANT_MEMBER);

UPDATE auth.role_report
SET is_active = 0,
    is_deleted = 1,
    deleted_at = @now,
    deleted_by = @system,
    updated_at = @now,
    updated_by = @system
WHERE is_deleted = 0
  AND role_id IN (@R_TENANT_ADMIN, @R_TENANT_MEMBER);

/* -------------------------------------------------------------------------
   5–6. Assignments: members lose tenant_member; admins keep/get tenant_admin
   ------------------------------------------------------------------------- */
UPDATE auth.user_role
SET is_active = 0,
    is_deleted = 1,
    deleted_at = @now,
    deleted_by = @system,
    updated_at = @now,
    updated_by = @system
WHERE is_deleted = 0
  AND account_id IS NULL
  AND role_id = @R_TENANT_MEMBER;

INSERT INTO auth.user_role (id, tenant_id, user_id, account_id, role_id, user_scope)
SELECT
    LEFT('01JRACF05' + CONVERT(varchar(64), HASHBYTES(
        'SHA2_256', CONCAT(N'ur|', tu.tenant_id, N'|', tu.user_id, N'|', @R_TENANT_ADMIN)), 2), 26),
    tu.tenant_id,
    tu.user_id,
    NULL,
    @R_TENANT_ADMIN,
    'tenant'
FROM auth.tenant_user AS tu
JOIN tenant.tenant AS t ON t.id = tu.tenant_id AND t.is_deleted = 0
WHERE tu.is_deleted = 0
  AND tu.role = 'admin'
  AND NOT EXISTS (
        SELECT 1
        FROM auth.user_role AS ur
        WHERE ur.tenant_id = tu.tenant_id
          AND ur.user_id = tu.user_id
          AND ur.account_id IS NULL
          AND ur.role_id = @R_TENANT_ADMIN
          AND ur.is_deleted = 0
  );

/* -------------------------------------------------------------------------
   7. lg: keep a@lg.com as admin; soft-delete other staff
   ------------------------------------------------------------------------- */
DECLARE @lg varchar(26) = (
    SELECT TOP 1 id FROM tenant.tenant WHERE subdomain = 'lg' AND is_deleted = 0
);
DECLARE @a_lg varchar(26) = (
    SELECT id FROM auth.app_user WHERE email_normalized = 'a@lg.com' AND is_deleted = 0
);

IF @lg IS NOT NULL AND @a_lg IS NOT NULL
BEGIN
    UPDATE auth.tenant_user
    SET role = 'admin', updated_at = @now
    WHERE tenant_id = @lg AND user_id = @a_lg AND is_deleted = 0;

    IF NOT EXISTS (
        SELECT 1 FROM auth.user_role
        WHERE tenant_id = @lg AND user_id = @a_lg AND account_id IS NULL
          AND role_id = @R_TENANT_ADMIN AND is_deleted = 0
    )
        INSERT INTO auth.user_role (id, tenant_id, user_id, account_id, role_id, user_scope)
        VALUES (
            LEFT('01JRACF05' + CONVERT(varchar(64), HASHBYTES(
                'SHA2_256', CONCAT(N'ur|', @lg, N'|', @a_lg, N'|', @R_TENANT_ADMIN)), 2), 26),
            @lg, @a_lg, NULL, @R_TENANT_ADMIN, 'tenant'
        );

    UPDATE ur
    SET is_active = 0, is_deleted = 1, deleted_at = @now, deleted_by = @system,
        updated_at = @now, updated_by = @system
    FROM auth.user_role AS ur
    JOIN auth.tenant_user AS tu
      ON tu.tenant_id = ur.tenant_id AND tu.user_id = ur.user_id AND tu.is_deleted = 0
    WHERE ur.tenant_id = @lg
      AND ur.is_deleted = 0
      AND tu.user_id <> @a_lg;

    UPDATE auth.tenant_user
    SET is_active = 0, is_deleted = 1, deleted_by = @system, updated_at = @now, updated_by = @system
    WHERE tenant_id = @lg AND is_deleted = 0 AND user_id <> @a_lg;
END;

/* -------------------------------------------------------------------------
   8. Flag unused: new mental model is members never have a default template
   ------------------------------------------------------------------------- */
IF COL_LENGTH('auth.tenant_user', 'default_member_role_enabled') IS NOT NULL
BEGIN
    EXEC sys.sp_executesql N'
        UPDATE auth.tenant_user
        SET default_member_role_enabled = 0, updated_at = SYSUTCDATETIME()
        WHERE is_deleted = 0 AND role = ''member'' AND default_member_role_enabled = 1';
END;

COMMIT TRANSACTION;
GO
