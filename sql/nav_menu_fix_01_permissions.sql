/*
    nav_menu_fix_01_permissions.sql
    Database: deevo_app_dev2
    Requires: nav.screen, auth_rbac_seed_tenant_catalog_v1.sql (template roles + WF menu perms)

    Per-user nav: the nav endpoints now return only what the caller may open.

      report item   visible when the caller has role_report.can_view for that report
                    (same rule as GET /api/reports)
      screen item   visible when the caller holds nav.screen.permission_code
                    (a screen with no permission_code is hidden from tenant and
                    portal callers; system callers are never filtered)
      group         visible when at least one child is
      module        listed when at least one item in it is visible

    1. nav.screen.permission_code  varchar(150) NULL
    2. Catalog rows for the screens that had no permission:
         menu.crm_lookups.view            CRM      tenant_admin + tenant_member
         menu.admin_users.view            GENERAL  tenant_admin
         menu.admin_portal_accounts.view  GENERAL  tenant_admin
       Admin screens are admin-only. Reference Data is grantable via custom roles only (not on tenant_admin).
    3. permission_code for every existing tenant nav screen:
         wf_inbox / wf_mine / wf_all / wf_templates -> menu.<code>.view
         crm_notes                                   -> screen.note.view
         crm_lookups / admin_users / admin_portal_accounts -> menu.<code>.view

    Apply AFTER auth_rbac_seed_tenant_catalog_v1.sql, as deevo. Safe to rerun.
    Does not change any user's roles or any custom role.
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

USE [deevo_app_dev2];
GO

IF COL_LENGTH('nav.screen', 'permission_code') IS NULL
    ALTER TABLE nav.screen ADD permission_code varchar(150) NULL;
GO

BEGIN TRANSACTION;

DECLARE @R_TENANT_ADMIN  varchar(26) = (
    SELECT id FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_admin' AND is_deleted = 0
);
DECLARE @R_TENANT_MEMBER varchar(26) = (
    SELECT id FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_member' AND is_deleted = 0
);
IF @R_TENANT_ADMIN IS NULL OR @R_TENANT_MEMBER IS NULL
    THROW 51040, N'Platform tenant_admin / tenant_member missing. Apply sql/auth_rbac_seed_v3.sql first.', 1;

DECLARE @Catalog TABLE (
    id                  varchar(26)   NOT NULL PRIMARY KEY,
    code                varchar(150)  NOT NULL,
    resource_code       varchar(100)  NOT NULL,
    description         nvarchar(300) NOT NULL,
    module_code         varchar(50)   NOT NULL,
    resource_name       nvarchar(100) NOT NULL,
    sort_order          int           NOT NULL,
    admin_grant_id      varchar(26)   NOT NULL,
    member_grant_id     varchar(26)   NULL
);

INSERT INTO @Catalog (
    id, code, resource_code, description, module_code, resource_name, sort_order,
    admin_grant_id, member_grant_id
) VALUES
    ('01JRACNAVPM000000000000001', 'menu.crm_lookups.view',           'crm_lookups',           N'Open CRM Reference Data',   'CRM',     N'Reference Data',   70, NULL, NULL),
    ('01JRACNAVPM000000000000002', 'menu.admin_users.view',           'admin_users',           N'Open Admin Users',          'GENERAL', N'Admin Users',      30, '01JRACNAVGA000000000000002', NULL),
    ('01JRACNAVPM000000000000003', 'menu.admin_portal_accounts.view', 'admin_portal_accounts', N'Open Admin Portal Accounts','GENERAL', N'Admin Portal Accounts', 40, '01JRACNAVGA000000000000003', NULL);

INSERT INTO auth.permission (
    id, code, resource_type, resource_code, action, user_scope, description,
    module_code, resource_name, sort_order, is_tenant_grantable
)
SELECT
    c.id, c.code, 'menu', c.resource_code, 'view', 'tenant', c.description,
    c.module_code, c.resource_name, c.sort_order, 1
FROM @Catalog AS c
WHERE NOT EXISTS (
    SELECT 1
    FROM auth.permission AS p
    WHERE p.user_scope = 'tenant'
      AND p.code = c.code
      AND p.is_deleted = 0
);

INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
SELECT c.admin_grant_id, @R_TENANT_ADMIN, p.id, 'tenant'
FROM @Catalog AS c
JOIN auth.permission AS p
    ON p.user_scope = 'tenant' AND p.code = c.code AND p.is_deleted = 0
WHERE NOT EXISTS (
    SELECT 1
    FROM auth.role_permission AS rp
    WHERE rp.role_id = @R_TENANT_ADMIN
      AND rp.permission_id = p.id
      AND rp.is_deleted = 0
);

INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
SELECT c.member_grant_id, @R_TENANT_MEMBER, p.id, 'tenant'
FROM @Catalog AS c
JOIN auth.permission AS p
    ON p.user_scope = 'tenant' AND p.code = c.code AND p.is_deleted = 0
WHERE c.member_grant_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM auth.role_permission AS rp
      WHERE rp.role_id = @R_TENANT_MEMBER
        AND rp.permission_id = p.id
        AND rp.is_deleted = 0
  );

DECLARE @ScreenPerm TABLE (
    screen_code     varchar(100) NOT NULL PRIMARY KEY,
    permission_code varchar(150) NOT NULL
);
INSERT INTO @ScreenPerm (screen_code, permission_code) VALUES
    ('wf_inbox',               'menu.wf_inbox.view'),
    ('wf_mine',                'menu.wf_mine.view'),
    ('wf_all',                 'menu.wf_all.view'),
    ('wf_templates',           'menu.wf_templates.view'),
    ('crm_notes',              'screen.note.view'),
    ('crm_lookups',            'menu.crm_lookups.view'),
    ('admin_users',            'menu.admin_users.view'),
    ('admin_portal_accounts',  'menu.admin_portal_accounts.view');

UPDATE s
SET permission_code = m.permission_code,
    updated_at = SYSUTCDATETIME()
FROM nav.screen AS s
JOIN @ScreenPerm AS m ON m.screen_code = s.code
WHERE s.user_scope = 'tenant'
  AND s.is_deleted = 0
  AND ISNULL(s.permission_code, '') <> m.permission_code;


-- rbac_fix_05: tenant_admin must not keep CRM lookups
UPDATE rp
SET is_active = 0, is_deleted = 1, deleted_at = SYSUTCDATETIME(), deleted_by = '01HYSTEM00000000000000000',
    updated_at = SYSUTCDATETIME(), updated_by = '01HYSTEM00000000000000000'
FROM auth.role_permission AS rp
JOIN auth.permission AS p ON p.id = rp.permission_id
JOIN auth.role AS r ON r.id = rp.role_id
WHERE rp.is_deleted = 0
  AND r.tenant_id IS NULL AND r.code = 'tenant_admin'
  AND p.code = 'menu.crm_lookups.view';

COMMIT TRANSACTION;
GO
