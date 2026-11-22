/*
    rbac_fix_01_tenant_integrity.sql
    Database: deevo_app_dev2

    Additive RBAC v3 fix: grant rows must stay inside one tenant.

    Apply AFTER sql/auth_rbac_schema_v3.sql, as deevo_ddl (ALTER TABLE).
    Safe to rerun.

    Step 0  Existing rows that break the new rules — THROW 51000 if any.
            Composite FKs (Step 2) validate EVERY row, including is_deleted = 1.
            Soft-delete does not satisfy those FKs: fix account_id/tenant_id
            or hard-delete the row, then rerun.
    Step 1  tenant.tenant_account: UNIQUE (id, tenant_id)
    Step 2  Composite FKs so account_id and tenant_id always agree
              auth.user_role           (account_id, tenant_id)
                -> tenant.tenant_account (id, tenant_id)
              auth.tenant_account_user (account_id, tenant_id)
                -> tenant.tenant_account (id, tenant_id)
            MATCH SIMPLE is intended: user_role.account_id is NULL for
            system/tenant rows (CK_user_role_scope_shape), so the FK fires
            only for portal rows. tenant_account_user has both columns
            NOT NULL, so it always fires.
    Step 3  Triggers for rules a FK cannot express (template roles have
            tenant_id NULL). Live rows only (is_deleted = 0).
              auth.user_role            role in same tenant or a template;
                                        user is a live member (is_deleted = 0).
                                        Inactive membership is allowed; the
                                        resolver still requires is_active = 1.
              auth.role_report          role in same tenant or a template,
                                        not system scope; report is system or
                                        belongs to the same tenant
              auth.default_role_report  role is a platform template, not
                                        system scope; report is system scope
    Step 4  Guards on the parent side
              auth.role.tenant_id and user_scope are immutable
              rpt.report_definition tenant_id / scope_type can't change
              while live grants use it

    Error numbers: 51000-51010

    SQLAlchemy: AFTER triggers forbid INSERT/UPDATE OUTPUT without INTO
    (error 334). Models for these tables set implicit_returning=False.
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

USE [deevo_app_dev2];
GO

/* ============================================================
   Step 0. Existing violations — abort if any.
   ============================================================ */
DECLARE @violations TABLE (
    problem varchar(80) NOT NULL,
    id      varchar(26) NOT NULL
);

INSERT INTO @violations (problem, id)
SELECT 'user_role: account in another tenant', ur.id
FROM auth.user_role ur
JOIN tenant.tenant_account ta ON ta.id = ur.account_id
WHERE ta.tenant_id <> ur.tenant_id
UNION ALL
SELECT 'tenant_account_user: account in another tenant', tau.id
FROM auth.tenant_account_user tau
JOIN tenant.tenant_account ta ON ta.id = tau.account_id
WHERE ta.tenant_id <> tau.tenant_id
UNION ALL
SELECT 'user_role: role deleted or in another tenant', ur.id
FROM auth.user_role ur
JOIN auth.role r ON r.id = ur.role_id
WHERE ur.is_deleted = 0
  AND (r.is_deleted = 1
       OR (r.tenant_id IS NOT NULL
           AND (ur.tenant_id IS NULL OR r.tenant_id <> ur.tenant_id)))
UNION ALL
SELECT 'user_role: user not a member of tenant', ur.id
FROM auth.user_role ur
WHERE ur.is_deleted = 0 AND ur.user_scope = 'tenant'
  AND NOT EXISTS (
        SELECT 1 FROM auth.tenant_user tu
        WHERE tu.tenant_id = ur.tenant_id
          AND tu.user_id = ur.user_id
          AND tu.is_deleted = 0)
UNION ALL
SELECT 'user_role: user not a member of account', ur.id
FROM auth.user_role ur
WHERE ur.is_deleted = 0 AND ur.user_scope = 'tenant_account'
  AND NOT EXISTS (
        SELECT 1 FROM auth.tenant_account_user tau
        WHERE tau.tenant_id = ur.tenant_id
          AND tau.account_id = ur.account_id
          AND tau.user_id = ur.user_id
          AND tau.is_deleted = 0)
UNION ALL
SELECT 'role_report: role invalid for tenant', rr.id
FROM auth.role_report rr
JOIN auth.role r ON r.id = rr.role_id
WHERE rr.is_deleted = 0
  AND (r.is_deleted = 1
       OR r.user_scope = 'system'
       OR (r.tenant_id IS NOT NULL AND r.tenant_id <> rr.tenant_id))
UNION ALL
SELECT 'role_report: report invalid for tenant', rr.id
FROM auth.role_report rr
JOIN rpt.report_definition d ON d.id = rr.report_id
WHERE rr.is_deleted = 0
  AND (d.is_deleted = 1
       OR (d.scope_type = 'tenant' AND d.tenant_id <> rr.tenant_id))
UNION ALL
SELECT 'default_role_report: role not a platform template', drr.id
FROM auth.default_role_report drr
JOIN auth.role r ON r.id = drr.role_id
WHERE drr.is_deleted = 0
  AND (r.is_deleted = 1 OR r.tenant_id IS NOT NULL OR r.user_scope = 'system')
UNION ALL
SELECT 'default_role_report: report not system scope', drr.id
FROM auth.default_role_report drr
JOIN rpt.report_definition d ON d.id = drr.report_id
WHERE drr.is_deleted = 0
  AND (d.is_deleted = 1 OR d.scope_type <> 'system');

IF EXISTS (SELECT 1 FROM @violations)
BEGIN
    DECLARE @list nvarchar(2048);
    SELECT @list = STRING_AGG(CONCAT(problem, N' ', id), N'; ')
                   WITHIN GROUP (ORDER BY problem, id)
    FROM @violations;
    SET @list = N'Step 0 tenant-integrity violations (fix account_id/tenant_id or hard-delete; soft-delete will not pass the FKs): '
              + ISNULL(@list, N'(unknown)');
    IF LEN(@list) > 2000
        SET @list = LEFT(@list, 2000) + N'…';
    THROW 51000, @list, 1;
END;
GO

/* ============================================================
   Step 1. tenant_account (id, tenant_id) as a FK target
   ============================================================ */
IF NOT EXISTS (
    SELECT 1 FROM sys.key_constraints
    WHERE name = 'UQ_tenant_account_id_tenant_id'
      AND parent_object_id = OBJECT_ID('tenant.tenant_account')
)
    ALTER TABLE tenant.tenant_account
        ADD CONSTRAINT UQ_tenant_account_id_tenant_id
        UNIQUE NONCLUSTERED (id, tenant_id);
GO

/* ============================================================
   Step 2. Composite FKs: account must belong to the row's tenant
   ============================================================ */
IF EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = 'FK_user_role_account_id'
      AND parent_object_id = OBJECT_ID('auth.user_role')
)
    ALTER TABLE auth.user_role DROP CONSTRAINT FK_user_role_account_id;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = 'FK_user_role_account_tenant'
      AND parent_object_id = OBJECT_ID('auth.user_role')
)
    ALTER TABLE auth.user_role WITH CHECK
        ADD CONSTRAINT FK_user_role_account_tenant
        FOREIGN KEY (account_id, tenant_id)
        REFERENCES tenant.tenant_account (id, tenant_id);
GO

IF EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = 'FK_tenant_account_user_account_id'
      AND parent_object_id = OBJECT_ID('auth.tenant_account_user')
)
    ALTER TABLE auth.tenant_account_user DROP CONSTRAINT FK_tenant_account_user_account_id;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = 'FK_tenant_account_user_account_tenant'
      AND parent_object_id = OBJECT_ID('auth.tenant_account_user')
)
    ALTER TABLE auth.tenant_account_user WITH CHECK
        ADD CONSTRAINT FK_tenant_account_user_account_tenant
        FOREIGN KEY (account_id, tenant_id)
        REFERENCES tenant.tenant_account (id, tenant_id);
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
   Step 4b. rpt.report_definition: scope can't move while granted
   ============================================================ */
CREATE OR ALTER TRIGGER rpt.TR_report_definition_scope_guard
ON rpt.report_definition
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF NOT (UPDATE(tenant_id) OR UPDATE(scope_type)) RETURN;

    DECLARE @id varchar(26), @msg nvarchar(400);

    SELECT TOP (1) @id = i.id
    FROM inserted i
    JOIN deleted d ON d.id = i.id
    WHERE (ISNULL(i.tenant_id, '') <> ISNULL(d.tenant_id, '') OR i.scope_type <> d.scope_type)
      AND (
            EXISTS (
                SELECT 1 FROM auth.role_report rr
                WHERE rr.report_id = i.id AND rr.is_deleted = 0)
         OR EXISTS (
                SELECT 1 FROM auth.default_role_report drr
                WHERE drr.report_id = i.id AND drr.is_deleted = 0)
          );
    IF @id IS NOT NULL
    BEGIN
        SET @msg = CONCAT(
            N'rpt.report_definition ', @id,
            N': tenant_id/scope_type cannot change while live role_report or default_role_report rows use it.');
        THROW 51009, @msg, 1;
    END;
END;
GO
