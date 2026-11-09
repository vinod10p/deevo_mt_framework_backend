/*
auth_rbac_seed_v3.sql
Idempotent platform seed for RBAC v3.

Run in SSMS as deevo_ddl (or deevo_app — these tables are mutable catalogs)
AFTER auth_rbac_schema_v3.sql. Safe to re-run: insert only when code / pair
is missing among live rows. IDs are literals (prefix 01JRACMTF) so every
environment gets the same primary keys.

Does not assign users (see auth_rbac_backfill_v3.sql) and does not copy
default_role_report into tenants (onboarding / backfill).

Permission action is view|create|update|delete|export|import|approve
(CK_permission_action). The plan name api.auth.role.manage is seeded as
api.auth.role.update (tenant) and api.system.role.update (system).

Platform roles (tenant_id NULL, is_system = 1):
  tenant_admin, tenant_member, account_admin, account_member, system_admin

Screen permissions: screen.lead.* (the only txn.screen on deevo_app_dev2).
Default report grants: the five MTF sample reports, plus crm_lead_list /
crm_lead_summary when those system reports exist.
*/

USE [deevo_app_dev2];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRANSACTION;

/* -------------------------------------------------------------------------
   1. Permissions — insert by code, then resolve the live id (literal on create)
   ------------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM auth.permission WHERE code = 'screen.lead.view' AND is_deleted = 0)
    INSERT INTO auth.permission (id, code, resource_type, resource_code, action, user_scope, description)
    VALUES ('01JRACMTFPM000000000000001', 'screen.lead.view', 'screen', 'lead', 'view', 'tenant',
            N'Open the Lead screen, list and read records');
IF NOT EXISTS (SELECT 1 FROM auth.permission WHERE code = 'screen.lead.create' AND is_deleted = 0)
    INSERT INTO auth.permission (id, code, resource_type, resource_code, action, user_scope, description)
    VALUES ('01JRACMTFPM000000000000002', 'screen.lead.create', 'screen', 'lead', 'create', 'tenant',
            N'Create a Lead');
IF NOT EXISTS (SELECT 1 FROM auth.permission WHERE code = 'screen.lead.update' AND is_deleted = 0)
    INSERT INTO auth.permission (id, code, resource_type, resource_code, action, user_scope, description)
    VALUES ('01JRACMTFPM000000000000003', 'screen.lead.update', 'screen', 'lead', 'update', 'tenant',
            N'Edit a Lead');
IF NOT EXISTS (SELECT 1 FROM auth.permission WHERE code = 'screen.lead.delete' AND is_deleted = 0)
    INSERT INTO auth.permission (id, code, resource_type, resource_code, action, user_scope, description)
    VALUES ('01JRACMTFPM000000000000004', 'screen.lead.delete', 'screen', 'lead', 'delete', 'tenant',
            N'Delete a Lead');
IF NOT EXISTS (SELECT 1 FROM auth.permission WHERE code = 'screen.lead.export' AND is_deleted = 0)
    INSERT INTO auth.permission (id, code, resource_type, resource_code, action, user_scope, description)
    VALUES ('01JRACMTFPM000000000000005', 'screen.lead.export', 'screen', 'lead', 'export', 'tenant',
            N'Export Leads');
IF NOT EXISTS (SELECT 1 FROM auth.permission WHERE code = 'api.auth.role.update' AND is_deleted = 0)
    INSERT INTO auth.permission (id, code, resource_type, resource_code, action, user_scope, description)
    VALUES ('01JRACMTFPM000000000000006', 'api.auth.role.update', 'api', 'auth.role', 'update', 'tenant',
            N'Manage tenant roles, grants and assignments');
IF NOT EXISTS (SELECT 1 FROM auth.permission WHERE code = 'api.system.role.update' AND is_deleted = 0)
    INSERT INTO auth.permission (id, code, resource_type, resource_code, action, user_scope, description)
    VALUES ('01JRACMTFPM000000000000007', 'api.system.role.update', 'api', 'system.role', 'update', 'system',
            N'Manage platform roles and the permission catalog');

DECLARE @P_LEAD_VIEW     varchar(26) = (SELECT id FROM auth.permission WHERE code = 'screen.lead.view' AND is_deleted = 0);
DECLARE @P_LEAD_CREATE   varchar(26) = (SELECT id FROM auth.permission WHERE code = 'screen.lead.create' AND is_deleted = 0);
DECLARE @P_LEAD_UPDATE   varchar(26) = (SELECT id FROM auth.permission WHERE code = 'screen.lead.update' AND is_deleted = 0);
DECLARE @P_LEAD_DELETE   varchar(26) = (SELECT id FROM auth.permission WHERE code = 'screen.lead.delete' AND is_deleted = 0);
DECLARE @P_LEAD_EXPORT   varchar(26) = (SELECT id FROM auth.permission WHERE code = 'screen.lead.export' AND is_deleted = 0);
DECLARE @P_TENANT_ROLE   varchar(26) = (SELECT id FROM auth.permission WHERE code = 'api.auth.role.update' AND is_deleted = 0);
DECLARE @P_SYSTEM_ROLE   varchar(26) = (SELECT id FROM auth.permission WHERE code = 'api.system.role.update' AND is_deleted = 0);

/* -------------------------------------------------------------------------
   2. Platform template roles
   ------------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_admin' AND is_deleted = 0)
    INSERT INTO auth.role (id, tenant_id, code, name, description, user_scope, is_system)
    VALUES ('01JRACMTFR1000000000000001', NULL, 'tenant_admin', N'Tenant Admin',
            N'Full tenant access, including role management', 'tenant', 1);
IF NOT EXISTS (SELECT 1 FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_member' AND is_deleted = 0)
    INSERT INTO auth.role (id, tenant_id, code, name, description, user_scope, is_system)
    VALUES ('01JRACMTFR1000000000000002', NULL, 'tenant_member', N'Tenant Member',
            N'Standard tenant staff (view)', 'tenant', 1);
IF NOT EXISTS (SELECT 1 FROM auth.role WHERE tenant_id IS NULL AND code = 'account_admin' AND is_deleted = 0)
    INSERT INTO auth.role (id, tenant_id, code, name, description, user_scope, is_system)
    VALUES ('01JRACMTFR1000000000000003', NULL, 'account_admin', N'Account Admin',
            N'Portal administrator for one account', 'tenant_account', 1);
IF NOT EXISTS (SELECT 1 FROM auth.role WHERE tenant_id IS NULL AND code = 'account_member' AND is_deleted = 0)
    INSERT INTO auth.role (id, tenant_id, code, name, description, user_scope, is_system)
    VALUES ('01JRACMTFR1000000000000004', NULL, 'account_member', N'Account Member',
            N'Portal member for one account', 'tenant_account', 1);
IF NOT EXISTS (SELECT 1 FROM auth.role WHERE tenant_id IS NULL AND code = 'system_admin' AND is_deleted = 0)
    INSERT INTO auth.role (id, tenant_id, code, name, description, user_scope, is_system)
    VALUES ('01JRACMTFR1000000000000005', NULL, 'system_admin', N'System Admin',
            N'Platform catalog and role administration', 'system', 1);

DECLARE @R_TENANT_ADMIN   varchar(26) = (SELECT id FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_admin' AND is_deleted = 0);
DECLARE @R_TENANT_MEMBER  varchar(26) = (SELECT id FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_member' AND is_deleted = 0);
DECLARE @R_ACCOUNT_ADMIN  varchar(26) = (SELECT id FROM auth.role WHERE tenant_id IS NULL AND code = 'account_admin' AND is_deleted = 0);
DECLARE @R_ACCOUNT_MEMBER varchar(26) = (SELECT id FROM auth.role WHERE tenant_id IS NULL AND code = 'account_member' AND is_deleted = 0);
DECLARE @R_SYSTEM_ADMIN   varchar(26) = (SELECT id FROM auth.role WHERE tenant_id IS NULL AND code = 'system_admin' AND is_deleted = 0);

/* -------------------------------------------------------------------------
   3. Role → permission grants
   ------------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM auth.role_permission WHERE role_id = @R_TENANT_ADMIN AND permission_id = @P_LEAD_VIEW AND is_deleted = 0)
    INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
    VALUES ('01JRACMTFGP000000000000001', @R_TENANT_ADMIN, @P_LEAD_VIEW, 'tenant');
IF NOT EXISTS (SELECT 1 FROM auth.role_permission WHERE role_id = @R_TENANT_ADMIN AND permission_id = @P_LEAD_CREATE AND is_deleted = 0)
    INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
    VALUES ('01JRACMTFGP000000000000002', @R_TENANT_ADMIN, @P_LEAD_CREATE, 'tenant');
IF NOT EXISTS (SELECT 1 FROM auth.role_permission WHERE role_id = @R_TENANT_ADMIN AND permission_id = @P_LEAD_UPDATE AND is_deleted = 0)
    INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
    VALUES ('01JRACMTFGP000000000000003', @R_TENANT_ADMIN, @P_LEAD_UPDATE, 'tenant');
IF NOT EXISTS (SELECT 1 FROM auth.role_permission WHERE role_id = @R_TENANT_ADMIN AND permission_id = @P_LEAD_DELETE AND is_deleted = 0)
    INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
    VALUES ('01JRACMTFGP000000000000004', @R_TENANT_ADMIN, @P_LEAD_DELETE, 'tenant');
IF NOT EXISTS (SELECT 1 FROM auth.role_permission WHERE role_id = @R_TENANT_ADMIN AND permission_id = @P_LEAD_EXPORT AND is_deleted = 0)
    INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
    VALUES ('01JRACMTFGP000000000000005', @R_TENANT_ADMIN, @P_LEAD_EXPORT, 'tenant');
IF NOT EXISTS (SELECT 1 FROM auth.role_permission WHERE role_id = @R_TENANT_ADMIN AND permission_id = @P_TENANT_ROLE AND is_deleted = 0)
    INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
    VALUES ('01JRACMTFGP000000000000006', @R_TENANT_ADMIN, @P_TENANT_ROLE, 'tenant');
IF NOT EXISTS (SELECT 1 FROM auth.role_permission WHERE role_id = @R_TENANT_MEMBER AND permission_id = @P_LEAD_VIEW AND is_deleted = 0)
    INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
    VALUES ('01JRACMTFGP000000000000007', @R_TENANT_MEMBER, @P_LEAD_VIEW, 'tenant');
IF NOT EXISTS (SELECT 1 FROM auth.role_permission WHERE role_id = @R_SYSTEM_ADMIN AND permission_id = @P_SYSTEM_ROLE AND is_deleted = 0)
    INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
    VALUES ('01JRACMTFGP000000000000008', @R_SYSTEM_ADMIN, @P_SYSTEM_ROLE, 'system');

/* -------------------------------------------------------------------------
   4. default_role_report — skip a report_key that is not seeded yet
   ------------------------------------------------------------------------- */
DECLARE @Grant TABLE (
    id         varchar(26) NOT NULL PRIMARY KEY,
    role_id    varchar(26) NOT NULL,
    report_key varchar(100) NOT NULL,
    can_view   bit NOT NULL,
    can_export bit NOT NULL
);

INSERT INTO @Grant (id, role_id, report_key, can_view, can_export) VALUES
    ('01JRACMTFDR000000000000001', @R_TENANT_ADMIN,   'tenant_account_list',         1, 1),
    ('01JRACMTFDR000000000000002', @R_TENANT_ADMIN,   'tenant_account_summary',      1, 1),
    ('01JRACMTFDR000000000000003', @R_TENANT_ADMIN,   'tenant_account_address_list', 1, 1),
    ('01JRACMTFDR000000000000004', @R_TENANT_ADMIN,   'tenant_user_list',            1, 1),
    ('01JRACMTFDR000000000000005', @R_TENANT_ADMIN,   'portal_user_list',            1, 1),
    ('01JRACMTFDR000000000000006', @R_TENANT_ADMIN,   'crm_lead_list',               1, 1),
    ('01JRACMTFDR000000000000007', @R_TENANT_ADMIN,   'crm_lead_summary',            1, 1),
    ('01JRACMTFDR000000000000008', @R_TENANT_MEMBER,  'tenant_account_list',         1, 0),
    ('01JRACMTFDR000000000000009', @R_TENANT_MEMBER,  'tenant_account_summary',      1, 0),
    ('01JRACMTFDR00000000000000A', @R_TENANT_MEMBER,  'tenant_account_address_list', 1, 0),
    ('01JRACMTFDR00000000000000B', @R_TENANT_MEMBER,  'tenant_user_list',            1, 0),
    ('01JRACMTFDR00000000000000C', @R_TENANT_MEMBER,  'portal_user_list',            1, 0),
    ('01JRACMTFDR00000000000000D', @R_TENANT_MEMBER,  'crm_lead_list',               1, 0),
    ('01JRACMTFDR00000000000000E', @R_TENANT_MEMBER,  'crm_lead_summary',            1, 0),
    ('01JRACMTFDR00000000000000F', @R_ACCOUNT_ADMIN,  'tenant_account_list',         1, 1),
    ('01JRACMTFDR00000000000000G', @R_ACCOUNT_ADMIN,  'tenant_account_summary',      1, 1),
    ('01JRACMTFDR00000000000000H', @R_ACCOUNT_ADMIN,  'tenant_account_address_list', 1, 1),
    ('01JRACMTFDR00000000000000J', @R_ACCOUNT_ADMIN,  'tenant_user_list',            1, 1),
    ('01JRACMTFDR00000000000000K', @R_ACCOUNT_ADMIN,  'portal_user_list',            1, 1),
    ('01JRACMTFDR00000000000000M', @R_ACCOUNT_MEMBER, 'tenant_account_list',         1, 0),
    ('01JRACMTFDR00000000000000N', @R_ACCOUNT_MEMBER, 'tenant_account_summary',      1, 0),
    ('01JRACMTFDR00000000000000P', @R_ACCOUNT_MEMBER, 'tenant_account_address_list', 1, 0),
    ('01JRACMTFDR00000000000000Q', @R_ACCOUNT_MEMBER, 'tenant_user_list',            1, 0),
    ('01JRACMTFDR00000000000000R', @R_ACCOUNT_MEMBER, 'portal_user_list',            1, 0);

INSERT INTO auth.default_role_report (id, role_id, report_id, can_view, can_export)
SELECT g.id, g.role_id, d.id, g.can_view, g.can_export
FROM @Grant AS g
JOIN rpt.report_definition AS d
    ON d.report_key = g.report_key
   AND d.scope_type = 'system'
   AND d.is_deleted = 0
WHERE NOT EXISTS (
    SELECT 1
    FROM auth.default_role_report AS existing
    WHERE existing.role_id = g.role_id
      AND existing.report_id = d.id
      AND existing.is_deleted = 0
);

COMMIT TRANSACTION;
GO
