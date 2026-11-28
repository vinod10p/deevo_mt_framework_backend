/*
    dev3_13_integrity_triggers.sql
    Database: deevo_app_dev3
    Requires: auth, rpt and tenant tables (created and loaded)

    Copies the integrity triggers from deevo_app_dev2, unchanged except that every CREATE
    became CREATE OR ALTER (dev3_11 already copied rpt.TR_report_definition_scope_guard):
      * auth.TR_user_role_integrity          - role live and of the same tenant; staff must be
                                               tenant members, portal users account members
      * auth.TR_role_report_integrity        - role and report live and of the same tenant
      * auth.TR_default_role_report_integrity - platform template roles and system reports only
      * auth.TR_role_tenant_immutable        - a role's tenant_id and user_scope never change
      * tenant.TR_tenant_setting_rbac_screens_one_way - rbac.screens can only be turned on

    Business units need no change here: the composite FK (business_unit_id, tenant_id) on
    each table already keeps a row's unit inside its tenant.

    Not copied: the eight email.* updated_at triggers (the email schema is not in dev3 yet;
    copy them with the email migration).

    The models of these tables keep implicit_returning = False because SQL Server rejects
    OUTPUT without INTO on a table with triggers.

    Apply as the DDL/owner login. Safe to rerun.
*/
USE [deevo_app_dev3];
GO

/* ============================================================
   Step 3c. auth.default_role_report
   ============================================================ */
CREATE OR ALTER TRIGGER auth.TR_default_role_report_integrity
ON auth.default_role_report
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF NOT EXISTS (SELECT 1 FROM inserted WHERE is_deleted = 0) RETURN;

    DECLARE @id varchar(26), @msg nvarchar(400);

    -- Role: live platform template (tenant_id NULL), tenant or account scope
    SELECT TOP (1) @id = i.id
    FROM inserted i
    JOIN auth.role r ON r.id = i.role_id
    WHERE i.is_deleted = 0
      AND (r.is_deleted = 1 OR r.tenant_id IS NOT NULL OR r.user_scope = 'system');
    IF @id IS NOT NULL
    BEGIN
        SET @msg = CONCAT(N'auth.default_role_report ', @id, N': role must be a live platform template role (not system scope).');
        THROW 51006, @msg, 1;
    END;

    SET @id = NULL;

    -- Report: live, system scope
    SELECT TOP (1) @id = i.id
    FROM inserted i
    JOIN rpt.report_definition d ON d.id = i.report_id
    WHERE i.is_deleted = 0
      AND (d.is_deleted = 1 OR d.scope_type <> 'system');
    IF @id IS NOT NULL
    BEGIN
        SET @msg = CONCAT(N'auth.default_role_report ', @id, N': report must be a live system-scope report.');
        THROW 51007, @msg, 1;
    END;
END;
GO

/* ============================================================
   Step 4a. auth.role: tenant_id and user_scope never change
   ============================================================ */
CREATE OR ALTER TRIGGER auth.TR_role_tenant_immutable
ON auth.role
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF NOT (UPDATE(tenant_id) OR UPDATE(user_scope)) RETURN;

    IF EXISTS (
        SELECT 1
        FROM inserted i
        JOIN deleted d ON d.id = i.id
        WHERE ISNULL(i.tenant_id, '') <> ISNULL(d.tenant_id, '')
    )
        THROW 51008, N'auth.role.tenant_id cannot be changed. Create a new role instead.', 1;

    IF EXISTS (
        SELECT 1
        FROM inserted i
        JOIN deleted d ON d.id = i.id
        WHERE i.user_scope <> d.user_scope
    )
        THROW 51010, N'auth.role.user_scope cannot be changed. Create a new role instead.', 1;
END;
GO

/* ============================================================
   Step 3b. auth.role_report
   ============================================================ */
CREATE OR ALTER TRIGGER auth.TR_role_report_integrity
ON auth.role_report
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF NOT EXISTS (SELECT 1 FROM inserted WHERE is_deleted = 0) RETURN;

    DECLARE @id varchar(26), @msg nvarchar(400);

    -- Role: live, not system scope, template or this tenant's role
    SELECT TOP (1) @id = i.id
    FROM inserted i
    JOIN auth.role r ON r.id = i.role_id
    WHERE i.is_deleted = 0
      AND (r.is_deleted = 1
           OR r.user_scope = 'system'
           OR (r.tenant_id IS NOT NULL AND r.tenant_id <> i.tenant_id));
    IF @id IS NOT NULL
    BEGIN
        SET @msg = CONCAT(N'auth.role_report ', @id, N': role is deleted, system scope, or belongs to another tenant.');
        THROW 51004, @msg, 1;
    END;

    SET @id = NULL;

    -- Report: live, and system scope or owned by this tenant
    SELECT TOP (1) @id = i.id
    FROM inserted i
    JOIN rpt.report_definition d ON d.id = i.report_id
    WHERE i.is_deleted = 0
      AND (d.is_deleted = 1
           OR (d.scope_type = 'tenant' AND d.tenant_id <> i.tenant_id));
    IF @id IS NOT NULL
    BEGIN
        SET @msg = CONCAT(N'auth.role_report ', @id, N': report is deleted or belongs to another tenant.');
        THROW 51005, @msg, 1;
    END;
END;
GO

/* ============================================================
   Step 3a. auth.user_role
   ============================================================ */
CREATE OR ALTER TRIGGER auth.TR_user_role_integrity
ON auth.user_role
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF NOT EXISTS (SELECT 1 FROM inserted WHERE is_deleted = 0) RETURN;

    DECLARE @id varchar(26), @msg nvarchar(400);

    -- Role must be live, and either a platform template or this tenant's role
    SELECT TOP (1) @id = i.id
    FROM inserted i
    JOIN auth.role r ON r.id = i.role_id
    WHERE i.is_deleted = 0
      AND (r.is_deleted = 1
           OR (r.tenant_id IS NOT NULL
               AND (i.tenant_id IS NULL OR r.tenant_id <> i.tenant_id)));
    IF @id IS NOT NULL
    BEGIN
        SET @msg = CONCAT(N'auth.user_role ', @id, N': role is deleted or belongs to another tenant.');
        THROW 51001, @msg, 1;
    END;

    SET @id = NULL;

    -- Tenant-scope user must be a live member of the tenant
    SELECT TOP (1) @id = i.id
    FROM inserted i
    WHERE i.is_deleted = 0 AND i.user_scope = 'tenant'
      AND NOT EXISTS (
            SELECT 1 FROM auth.tenant_user tu
            WHERE tu.tenant_id = i.tenant_id
              AND tu.user_id = i.user_id
              AND tu.is_deleted = 0);
    IF @id IS NOT NULL
    BEGIN
        SET @msg = CONCAT(N'auth.user_role ', @id, N': user is not a member of this tenant (auth.tenant_user).');
        THROW 51002, @msg, 1;
    END;

    SET @id = NULL;

    -- Account-scope user must be a live member of the account
    SELECT TOP (1) @id = i.id
    FROM inserted i
    WHERE i.is_deleted = 0 AND i.user_scope = 'tenant_account'
      AND NOT EXISTS (
            SELECT 1 FROM auth.tenant_account_user tau
            WHERE tau.tenant_id = i.tenant_id
              AND tau.account_id = i.account_id
              AND tau.user_id = i.user_id
              AND tau.is_deleted = 0);
    IF @id IS NOT NULL
    BEGIN
        SET @msg = CONCAT(N'auth.user_role ', @id, N': user is not a member of this account (auth.tenant_account_user).');
        THROW 51003, @msg, 1;
    END;
END;
GO

/* ============================================================
   Step 2. rbac.screens is one-way
   ============================================================ */
CREATE OR ALTER TRIGGER tenant.TR_tenant_setting_rbac_screens_one_way
ON tenant.tenant_setting
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;

    IF EXISTS (
        SELECT 1
        FROM deleted d
        WHERE d.[key] = 'rbac.screens'
          AND NOT EXISTS (SELECT 1 FROM inserted i WHERE i.id = d.id)
    )
    BEGIN
        SET NOCOUNT OFF;
        THROW 51030, N'tenant.tenant_setting: rbac.screens cannot be deleted.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM inserted i
        WHERE i.[key] = 'rbac.screens'
          AND NOT EXISTS (SELECT 1 FROM deleted d WHERE d.id = i.id)
          AND (
                i.[value] IS NULL
             OR i.[value] <> N'on'
             OR i.is_active = 0
             OR i.is_deleted = 1
          )
    )
    BEGIN
        SET NOCOUNT OFF;
        THROW 51031, N'tenant.tenant_setting: rbac.screens can only be inserted as on.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM inserted i
        JOIN deleted d ON d.id = i.id
        WHERE d.[key] = 'rbac.screens'
          AND d.[value] = N'on'
          AND d.is_deleted = 0
          AND (
                i.[key] <> 'rbac.screens'
             OR i.[value] IS NULL
             OR i.[value] <> N'on'
             OR i.is_active = 0
             OR i.is_deleted = 1
          )
    )
    BEGIN
        SET NOCOUNT OFF;
        THROW 51032, N'tenant.tenant_setting: rbac.screens is one-way and cannot be turned off.', 1;
    END;

    SET NOCOUNT OFF;
END;
GO
