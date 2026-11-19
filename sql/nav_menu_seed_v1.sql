/*
nav_menu_seed_v1.sql
Tenant-scope nav catalog: CRM, WF, EMAIL.

Apply in SSMS as deevo_ddl (or deevo_app) AFTER nav_menu_schema_v1.sql
(recreate). Safe to re-run: insert only when the live (user_scope, code) /
(module_id, code) pair is missing. IDs are literals (prefix 01JNAVMTF).

menu_item.user_scope must match the module (composite FK). screen_id is omitted
on these rows (reports/groups only). Do not seed nav.screen.code = 'lead'.

Report items look up rpt.report_definition by report_key (system, live).
Missing keys are skipped so the seed still runs before product reports exist.

  CRM  (level-1 reports — skip a row if that report_key is not seeded)
    CRM.LEADS          crm_lead_list
    CRM.ACCOUNTS       crm_account_list
    CRM.CONTACTS       crm_contact_list
    CRM.OPPORTUNITIES  crm_opportunity_list
    CRM.TASKS          crm_task_list

  WF   (placeholders against MTF sample reports so the module is not empty)
    WF.TASKS           group
      WF.TASKS.MINE    tenant_user_list
      WF.TASKS.ALL     tenant_account_list

  EMAIL (placeholders)
    EMAIL.INBOX        tenant_account_list
    EMAIL.SENT         portal_user_list

Portal / system modules are not seeded in v1.
*/

USE [deevo_app_dev2];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRANSACTION;

/* -------------------------------------------------------------------------
   1. Modules
   ------------------------------------------------------------------------- */
IF NOT EXISTS (
    SELECT 1 FROM nav.menu_module
    WHERE user_scope = 'tenant' AND code = 'CRM' AND is_deleted = 0
)
    INSERT INTO nav.menu_module (id, code, name, icon, user_scope, sort_order)
    VALUES ('01JNAVMTFMD000000000000001', 'CRM', N'CRM', 'crm', 'tenant', 10);

IF NOT EXISTS (
    SELECT 1 FROM nav.menu_module
    WHERE user_scope = 'tenant' AND code = 'WF' AND is_deleted = 0
)
    INSERT INTO nav.menu_module (id, code, name, icon, user_scope, sort_order)
    VALUES ('01JNAVMTFMD000000000000002', 'WF', N'Workflow', 'workflow', 'tenant', 20);

IF NOT EXISTS (
    SELECT 1 FROM nav.menu_module
    WHERE user_scope = 'tenant' AND code = 'EMAIL' AND is_deleted = 0
)
    INSERT INTO nav.menu_module (id, code, name, icon, user_scope, sort_order)
    VALUES ('01JNAVMTFMD000000000000003', 'EMAIL', N'Email', 'mail', 'tenant', 30);

DECLARE @CRM   varchar(26) = (
    SELECT id FROM nav.menu_module
    WHERE user_scope = 'tenant' AND code = 'CRM' AND is_deleted = 0
);
DECLARE @WF    varchar(26) = (
    SELECT id FROM nav.menu_module
    WHERE user_scope = 'tenant' AND code = 'WF' AND is_deleted = 0
);
DECLARE @EMAIL varchar(26) = (
    SELECT id FROM nav.menu_module
    WHERE user_scope = 'tenant' AND code = 'EMAIL' AND is_deleted = 0
);

/* -------------------------------------------------------------------------
   2. Report lookups — skip a key that is not seeded yet
   ------------------------------------------------------------------------- */
DECLARE @R_LEAD varchar(26) = (
    SELECT TOP 1 id FROM rpt.report_definition
    WHERE report_key = 'crm_lead_list' AND scope_type = 'system'
      AND is_deleted = 0 AND is_active = 1
);
DECLARE @R_ACCOUNT varchar(26) = (
    SELECT TOP 1 id FROM rpt.report_definition
    WHERE report_key = 'crm_account_list' AND scope_type = 'system'
      AND is_deleted = 0 AND is_active = 1
);
DECLARE @R_CONTACT varchar(26) = (
    SELECT TOP 1 id FROM rpt.report_definition
    WHERE report_key = 'crm_contact_list' AND scope_type = 'system'
      AND is_deleted = 0 AND is_active = 1
);
DECLARE @R_OPP varchar(26) = (
    SELECT TOP 1 id FROM rpt.report_definition
    WHERE report_key = 'crm_opportunity_list' AND scope_type = 'system'
      AND is_deleted = 0 AND is_active = 1
);
DECLARE @R_TASK varchar(26) = (
    SELECT TOP 1 id FROM rpt.report_definition
    WHERE report_key = 'crm_task_list' AND scope_type = 'system'
      AND is_deleted = 0 AND is_active = 1
);
DECLARE @R_USER_LIST varchar(26) = (
    SELECT TOP 1 id FROM rpt.report_definition
    WHERE report_key = 'tenant_user_list' AND scope_type = 'system'
      AND is_deleted = 0 AND is_active = 1
);
DECLARE @R_ACCOUNT_LIST varchar(26) = (
    SELECT TOP 1 id FROM rpt.report_definition
    WHERE report_key = 'tenant_account_list' AND scope_type = 'system'
      AND is_deleted = 0 AND is_active = 1
);
DECLARE @R_PORTAL_USER varchar(26) = (
    SELECT TOP 1 id FROM rpt.report_definition
    WHERE report_key = 'portal_user_list' AND scope_type = 'system'
      AND is_deleted = 0 AND is_active = 1
);

/* -------------------------------------------------------------------------
   3. CRM — level-1 reports
   ------------------------------------------------------------------------- */
IF @R_LEAD IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM nav.menu_item
    WHERE module_id = @CRM AND code = 'CRM.LEADS' AND is_deleted = 0
)
    INSERT INTO nav.menu_item
        (id, module_id, user_scope, parent_id, code, item_type, label, icon, report_id, sort_order)
    VALUES
        ('01JNAVMTFME000000000000001', @CRM, 'tenant', NULL, 'CRM.LEADS', 'report',
         N'Leads', 'users', @R_LEAD, 10);

IF @R_ACCOUNT IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM nav.menu_item
    WHERE module_id = @CRM AND code = 'CRM.ACCOUNTS' AND is_deleted = 0
)
    INSERT INTO nav.menu_item
        (id, module_id, user_scope, parent_id, code, item_type, label, icon, report_id, sort_order)
    VALUES
        ('01JNAVMTFME000000000000002', @CRM, 'tenant', NULL, 'CRM.ACCOUNTS', 'report',
         N'Accounts', 'building', @R_ACCOUNT, 20);

IF @R_CONTACT IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM nav.menu_item
    WHERE module_id = @CRM AND code = 'CRM.CONTACTS' AND is_deleted = 0
)
    INSERT INTO nav.menu_item
        (id, module_id, user_scope, parent_id, code, item_type, label, icon, report_id, sort_order)
    VALUES
        ('01JNAVMTFME000000000000003', @CRM, 'tenant', NULL, 'CRM.CONTACTS', 'report',
         N'Contacts', 'contact', @R_CONTACT, 30);

IF @R_OPP IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM nav.menu_item
    WHERE module_id = @CRM AND code = 'CRM.OPPORTUNITIES' AND is_deleted = 0
)
    INSERT INTO nav.menu_item
        (id, module_id, user_scope, parent_id, code, item_type, label, icon, report_id, sort_order)
    VALUES
        ('01JNAVMTFME000000000000004', @CRM, 'tenant', NULL, 'CRM.OPPORTUNITIES', 'report',
         N'Opportunities', 'handshake', @R_OPP, 40);

IF @R_TASK IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM nav.menu_item
    WHERE module_id = @CRM AND code = 'CRM.TASKS' AND is_deleted = 0
)
    INSERT INTO nav.menu_item
        (id, module_id, user_scope, parent_id, code, item_type, label, icon, report_id, sort_order)
    VALUES
        ('01JNAVMTFME000000000000005', @CRM, 'tenant', NULL, 'CRM.TASKS', 'report',
         N'Tasks', 'checklist', @R_TASK, 50);

/* -------------------------------------------------------------------------
   4. WF — group with placeholder reports
   ------------------------------------------------------------------------- */
IF NOT EXISTS (
    SELECT 1 FROM nav.menu_item
    WHERE module_id = @WF AND code = 'WF.TASKS' AND is_deleted = 0
)
    INSERT INTO nav.menu_item
        (id, module_id, user_scope, parent_id, code, item_type, label, icon, report_id, sort_order)
    VALUES
        ('01JNAVMTFME000000000000006', @WF, 'tenant', NULL, 'WF.TASKS', 'group',
         N'Tasks', 'folder', NULL, 10);

DECLARE @WF_TASKS varchar(26) = (
    SELECT id FROM nav.menu_item
    WHERE module_id = @WF AND code = 'WF.TASKS' AND is_deleted = 0
);

IF @R_USER_LIST IS NOT NULL AND @WF_TASKS IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM nav.menu_item
    WHERE module_id = @WF AND code = 'WF.TASKS.MINE' AND is_deleted = 0
)
    INSERT INTO nav.menu_item
        (id, module_id, user_scope, parent_id, code, item_type, label, icon, report_id, sort_order)
    VALUES
        ('01JNAVMTFME000000000000007', @WF, 'tenant', @WF_TASKS, 'WF.TASKS.MINE', 'report',
         N'My tasks', 'user', @R_USER_LIST, 10);

IF @R_ACCOUNT_LIST IS NOT NULL AND @WF_TASKS IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM nav.menu_item
    WHERE module_id = @WF AND code = 'WF.TASKS.ALL' AND is_deleted = 0
)
    INSERT INTO nav.menu_item
        (id, module_id, user_scope, parent_id, code, item_type, label, icon, report_id, sort_order)
    VALUES
        ('01JNAVMTFME000000000000008', @WF, 'tenant', @WF_TASKS, 'WF.TASKS.ALL', 'report',
         N'All tasks', 'list', @R_ACCOUNT_LIST, 20);

/* -------------------------------------------------------------------------
   5. EMAIL — level-1 placeholder reports
   ------------------------------------------------------------------------- */
IF @R_ACCOUNT_LIST IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM nav.menu_item
    WHERE module_id = @EMAIL AND code = 'EMAIL.INBOX' AND is_deleted = 0
)
    INSERT INTO nav.menu_item
        (id, module_id, user_scope, parent_id, code, item_type, label, icon, report_id, sort_order)
    VALUES
        ('01JNAVMTFME000000000000009', @EMAIL, 'tenant', NULL, 'EMAIL.INBOX', 'report',
         N'Inbox', 'inbox', @R_ACCOUNT_LIST, 10);

IF @R_PORTAL_USER IS NOT NULL
AND NOT EXISTS (
    SELECT 1 FROM nav.menu_item
    WHERE module_id = @EMAIL AND code = 'EMAIL.SENT' AND is_deleted = 0
)
    INSERT INTO nav.menu_item
        (id, module_id, user_scope, parent_id, code, item_type, label, icon, report_id, sort_order)
    VALUES
        ('01JNAVMTFME00000000000000A', @EMAIL, 'tenant', NULL, 'EMAIL.SENT', 'report',
         N'Sent', 'send', @R_PORTAL_USER, 20);

COMMIT TRANSACTION;
GO
