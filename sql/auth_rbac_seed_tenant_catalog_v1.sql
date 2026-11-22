/*
auth_rbac_seed_tenant_catalog_v1.sql
Tenant Role Admin catalog: module_code, labels, sort_order, grantable flag,
CRM screen actions, WF menu view, and template-role grants.

Apply AFTER sql/auth_rbac_seed_v3.sql (and rbac_fix_02_permission_catalog.sql).
Safe to re-run: update live rows by (user_scope, code); insert only when missing.
IDs are literals (prefix 01JRACMTF). Existing DeevoFlow permission rows
(01JRACACC… / 01JRACCTC… / …) are updated in place, not duplicated.

CRM screens (txn.screen_key): lead, account, contact, opportunity, task, note
  actions view|create|update|delete|export, module_code CRM, grantable.
WF SPA (nav.screen.code): wf_inbox, wf_mine, wf_all, wf_templates
  menu.{code}.view, module_code WF, grantable.
GENERAL: api.auth.role.update (grantable), api.system.role.update (not).

tenant_admin: thin admin bundle only (api.auth.role.update). Other grants
come from rbac_fix_05 / nav_menu_fix_01 (admin menus) and custom roles.
tenant_member: no automatic grants (members start with empty RBAC).
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

USE [deevo_app_dev2];
GO

BEGIN TRANSACTION;

DECLARE @R_TENANT_ADMIN  varchar(26) = (
    SELECT id FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_admin' AND is_deleted = 0
);
DECLARE @R_TENANT_MEMBER varchar(26) = (
    SELECT id FROM auth.role WHERE tenant_id IS NULL AND code = 'tenant_member' AND is_deleted = 0
);
IF @R_TENANT_ADMIN IS NULL OR @R_TENANT_MEMBER IS NULL
    THROW 51020, N'Platform tenant_admin / tenant_member missing. Apply sql/auth_rbac_seed_v3.sql first.', 1;

DECLARE @Catalog TABLE (
    id                   varchar(26)   NOT NULL PRIMARY KEY,
    code                 varchar(150)  NOT NULL,
    resource_type        varchar(20)   NOT NULL,
    resource_code        varchar(100)  NOT NULL,
    action               varchar(20)   NOT NULL,
    user_scope           varchar(20)   NOT NULL,
    description          nvarchar(300) NULL,
    module_code          varchar(50)   NOT NULL,
    resource_name        nvarchar(100) NOT NULL,
    sort_order           int           NOT NULL,
    is_tenant_grantable  bit           NOT NULL,
    admin_grant_id       varchar(26)   NULL,
    member_grant_id      varchar(26)   NULL
);

INSERT INTO @Catalog (
    id, code, resource_type, resource_code, action, user_scope, description,
    module_code, resource_name, sort_order, is_tenant_grantable,
    admin_grant_id, member_grant_id
) VALUES
    -- CRM screens
    ('01JRACMTFPM000000000000001', 'screen.lead.view',     'screen', 'lead',         'view',   'tenant', N'Open the Lead screen, list and read records', 'CRM', N'Lead',         10, 1, '01JRACMTFGA000000000000001', '01JRACMTFGM000000000000001'),
    ('01JRACMTFPM000000000000002', 'screen.lead.create',   'screen', 'lead',         'create', 'tenant', N'Create a Lead',                               'CRM', N'Lead',         10, 1, '01JRACMTFGA000000000000002', NULL),
    ('01JRACMTFPM000000000000003', 'screen.lead.update',   'screen', 'lead',         'update', 'tenant', N'Edit a Lead',                                 'CRM', N'Lead',         10, 1, '01JRACMTFGA000000000000003', NULL),
    ('01JRACMTFPM000000000000004', 'screen.lead.delete',   'screen', 'lead',         'delete', 'tenant', N'Delete a Lead',                               'CRM', N'Lead',         10, 1, '01JRACMTFGA000000000000004', NULL),
    ('01JRACMTFPM000000000000005', 'screen.lead.export',   'screen', 'lead',         'export', 'tenant', N'Export Leads',                                'CRM', N'Lead',         10, 1, '01JRACMTFGA000000000000005', NULL),

    ('01JRACMTFPM000000000000020', 'screen.account.view',  'screen', 'account',      'view',   'tenant', N'Open the Account screen, list and read records', 'CRM', N'Account',      20, 1, '01JRACMTFGA000000000000006', '01JRACMTFGM000000000000002'),
    ('01JRACMTFPM000000000000021', 'screen.account.create','screen', 'account',      'create', 'tenant', N'Create an Account',                            'CRM', N'Account',      20, 1, '01JRACMTFGA000000000000007', NULL),
    ('01JRACMTFPM000000000000022', 'screen.account.update','screen', 'account',      'update', 'tenant', N'Edit an Account',                              'CRM', N'Account',      20, 1, '01JRACMTFGA000000000000008', NULL),
    ('01JRACMTFPM000000000000023', 'screen.account.delete','screen', 'account',      'delete', 'tenant', N'Delete an Account',                            'CRM', N'Account',      20, 1, '01JRACMTFGA000000000000009', NULL),
    ('01JRACMTFPM000000000000024', 'screen.account.export','screen', 'account',      'export', 'tenant', N'Export Accounts',                              'CRM', N'Account',      20, 1, '01JRACMTFGA00000000000000A', NULL),

    ('01JRACMTFPM000000000000025', 'screen.contact.view',  'screen', 'contact',      'view',   'tenant', N'Open the Contact screen, list and read records', 'CRM', N'Contact',      30, 1, '01JRACMTFGA00000000000000B', '01JRACMTFGM000000000000003'),
    ('01JRACMTFPM000000000000026', 'screen.contact.create','screen', 'contact',      'create', 'tenant', N'Create a Contact',                             'CRM', N'Contact',      30, 1, '01JRACMTFGA00000000000000C', NULL),
    ('01JRACMTFPM000000000000027', 'screen.contact.update','screen', 'contact',      'update', 'tenant', N'Edit a Contact',                               'CRM', N'Contact',      30, 1, '01JRACMTFGA00000000000000D', NULL),
    ('01JRACMTFPM000000000000028', 'screen.contact.delete','screen', 'contact',      'delete', 'tenant', N'Delete a Contact',                             'CRM', N'Contact',      30, 1, '01JRACMTFGA00000000000000E', NULL),
    ('01JRACMTFPM000000000000029', 'screen.contact.export','screen', 'contact',      'export', 'tenant', N'Export Contacts',                              'CRM', N'Contact',      30, 1, '01JRACMTFGA00000000000000F', NULL),

    ('01JRACMTFPM000000000000030', 'screen.opportunity.view',  'screen', 'opportunity', 'view',   'tenant', N'Open the Opportunity screen, list and read records', 'CRM', N'Opportunity', 40, 1, '01JRACMTFGA00000000000000G', '01JRACMTFGM000000000000004'),
    ('01JRACMTFPM000000000000031', 'screen.opportunity.create','screen', 'opportunity', 'create', 'tenant', N'Create an Opportunity',                       'CRM', N'Opportunity', 40, 1, '01JRACMTFGA00000000000000H', NULL),
    ('01JRACMTFPM000000000000032', 'screen.opportunity.update','screen', 'opportunity', 'update', 'tenant', N'Edit an Opportunity',                         'CRM', N'Opportunity', 40, 1, '01JRACMTFGA00000000000000J', NULL),
    ('01JRACMTFPM000000000000033', 'screen.opportunity.delete','screen', 'opportunity', 'delete', 'tenant', N'Delete an Opportunity',                       'CRM', N'Opportunity', 40, 1, '01JRACMTFGA00000000000000K', NULL),
    ('01JRACMTFPM000000000000034', 'screen.opportunity.export','screen', 'opportunity', 'export', 'tenant', N'Export Opportunities',                        'CRM', N'Opportunity', 40, 1, '01JRACMTFGA00000000000000M', NULL),

    ('01JRACMTFPM000000000000035', 'screen.task.view',     'screen', 'task',         'view',   'tenant', N'Open the Task screen, list and read records', 'CRM', N'Task',         50, 1, '01JRACMTFGA00000000000000N', '01JRACMTFGM000000000000005'),
    ('01JRACMTFPM000000000000036', 'screen.task.create',   'screen', 'task',         'create', 'tenant', N'Create a Task',                               'CRM', N'Task',         50, 1, '01JRACMTFGA00000000000000P', NULL),
    ('01JRACMTFPM000000000000037', 'screen.task.update',   'screen', 'task',         'update', 'tenant', N'Edit a Task',                                 'CRM', N'Task',         50, 1, '01JRACMTFGA00000000000000Q', NULL),
    ('01JRACMTFPM000000000000038', 'screen.task.delete',   'screen', 'task',         'delete', 'tenant', N'Delete a Task',                               'CRM', N'Task',         50, 1, '01JRACMTFGA00000000000000R', NULL),
    ('01JRACMTFPM000000000000039', 'screen.task.export',   'screen', 'task',         'export', 'tenant', N'Export Tasks',                                'CRM', N'Task',         50, 1, '01JRACMTFGA00000000000000S', NULL),

    ('01JRACMTFPM000000000000040', 'screen.note.view',     'screen', 'note',         'view',   'tenant', N'Open the Note screen, list and read records', 'CRM', N'Note',         60, 1, '01JRACMTFGA00000000000000T', '01JRACMTFGM000000000000006'),
    ('01JRACMTFPM000000000000041', 'screen.note.create',   'screen', 'note',         'create', 'tenant', N'Create a Note',                               'CRM', N'Note',         60, 1, '01JRACMTFGA00000000000000V', NULL),
    ('01JRACMTFPM000000000000042', 'screen.note.update',   'screen', 'note',         'update', 'tenant', N'Edit a Note',                                 'CRM', N'Note',         60, 1, '01JRACMTFGA00000000000000W', NULL),
    ('01JRACMTFPM000000000000043', 'screen.note.delete',   'screen', 'note',         'delete', 'tenant', N'Delete a Note',                               'CRM', N'Note',         60, 1, '01JRACMTFGA00000000000000X', NULL),
    ('01JRACMTFPM000000000000044', 'screen.note.export',   'screen', 'note',         'export', 'tenant', N'Export Notes',                                'CRM', N'Note',         60, 1, '01JRACMTFGA00000000000000Y', NULL),

    -- WF SPA (nav.screen.code)
    ('01JRACMTFPM000000000000010', 'menu.wf_inbox.view',     'menu', 'wf_inbox',     'view', 'tenant', N'Open Workflow Inbox',      'WF', N'Inbox',          10, 1, '01JRACMTFGA00000000000000Z', '01JRACMTFGM000000000000007'),
    ('01JRACMTFPM000000000000011', 'menu.wf_mine.view',      'menu', 'wf_mine',      'view', 'tenant', N'Open My Workflows',        'WF', N'My Workflows',   20, 1, '01JRACMTFGA000000000000010', '01JRACMTFGM000000000000008'),
    ('01JRACMTFPM000000000000012', 'menu.wf_all.view',       'menu', 'wf_all',       'view', 'tenant', N'Open All Workflows',       'WF', N'All Workflows',  30, 1, '01JRACMTFGA000000000000011', '01JRACMTFGM000000000000009'),
    ('01JRACMTFPM000000000000013', 'menu.wf_templates.view', 'menu', 'wf_templates', 'view', 'tenant', N'Open Workflow Templates',  'WF', N'Templates',      40, 1, '01JRACMTFGA000000000000012', '01JRACMTFGM00000000000000A'),

    -- GENERAL
    ('01JRACMTFPM000000000000006', 'api.auth.role.update',   'api', 'auth.role',   'update', 'tenant', N'Manage tenant roles, grants and assignments', 'GENERAL', N'Tenant roles', 10, 1, '01JRACMTFGA000000000000013', NULL),
    ('01JRACMTFPM000000000000007', 'api.system.role.update', 'api', 'system.role', 'update', 'system', N'Manage platform roles and the permission catalog', 'GENERAL', N'System roles', 20, 0, NULL, NULL);

UPDATE p
SET module_code = c.module_code,
    resource_name = c.resource_name,
    sort_order = c.sort_order,
    is_tenant_grantable = c.is_tenant_grantable,
    description = c.description,
    updated_at = SYSUTCDATETIME()
FROM auth.permission AS p
JOIN @Catalog AS c
    ON c.user_scope = p.user_scope
   AND c.code = p.code
WHERE p.is_deleted = 0
  AND (
        p.module_code <> c.module_code
     OR p.resource_name <> c.resource_name
     OR p.sort_order <> c.sort_order
     OR p.is_tenant_grantable <> c.is_tenant_grantable
     OR ISNULL(p.description, N'') <> ISNULL(c.description, N'')
  );

INSERT INTO auth.permission (
    id, code, resource_type, resource_code, action, user_scope, description,
    module_code, resource_name, sort_order, is_tenant_grantable
)
SELECT
    c.id, c.code, c.resource_type, c.resource_code, c.action, c.user_scope, c.description,
    c.module_code, c.resource_name, c.sort_order, c.is_tenant_grantable
FROM @Catalog AS c
WHERE NOT EXISTS (
    SELECT 1
    FROM auth.permission AS p
    WHERE p.user_scope = c.user_scope
      AND p.code = c.code
      AND p.is_deleted = 0
);

-- Thin tenant_admin: Role Admin only from this seed. Admin menus come from nav_menu_fix_01.
INSERT INTO auth.role_permission (id, role_id, permission_id, user_scope)
SELECT c.admin_grant_id, @R_TENANT_ADMIN, p.id, 'tenant'
FROM @Catalog AS c
JOIN auth.permission AS p
    ON p.user_scope = c.user_scope
   AND p.code = c.code
   AND p.is_deleted = 0
WHERE c.code = 'api.auth.role.update'
  AND c.admin_grant_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM auth.role_permission AS rp
      WHERE rp.role_id = @R_TENANT_ADMIN
        AND rp.permission_id = p.id
        AND rp.is_deleted = 0
  );

-- tenant_member receives no grants (members start empty; assign custom roles).


COMMIT TRANSACTION;
GO
