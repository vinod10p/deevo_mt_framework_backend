/*
    rbac_fix_02_permission_catalog.sql
    Database: deevo_app_dev2
    Requires: sql/auth_rbac_schema_v3.sql, sql/rbac_fix_01_tenant_integrity.sql

    Step 1 of tenant Role Admin: catalog columns the React grid needs,
    and unique (user_scope, code) so tenant and portal can share a code.

    Does NOT: compute permission.code, add role.source_role_id, change
    membership uniqueness, or add menu/report triggers. Those wait.

    Apply AFTER rbac_fix_01_tenant_integrity.sql, as deevo_ddl (ALTER TABLE).
    Safe to rerun.

    Step 0  THROW 51000 if live (user_scope, code) duplicates exist
            (the new unique index would fail).
    Step 1  module_code, resource_name, sort_order, is_tenant_grantable
            Existing rows: module_code = 'GENERAL'; resource_name from
            txn.screen.display_name, nav.screen.name, or resource_code.
            System-scope rows: is_tenant_grantable = 0 before the check.
            module_code has no lasting default — new rows must state it.
    Step 2  Drop UQ_permission_code (code only). Create
            UQ_permission_scope_code (user_scope, code) WHERE is_deleted = 0.
            IX_permission_admin_grid for the Role Admin list.

    Error numbers: 51000 (existing violations; 51001–51010 are fix_01).
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
SELECT 'permission: duplicate live (user_scope, code)', MIN(id)
FROM auth.permission
WHERE is_deleted = 0
GROUP BY user_scope, code
HAVING COUNT(*) > 1;

IF EXISTS (SELECT 1 FROM @violations)
BEGIN
    DECLARE @msg nvarchar(400);
    SELECT @msg = CONCAT(
        N'rbac_fix_02_permission_catalog: existing rows break the new unique index. ',
        N'Fix them, then rerun. ',
        STRING_AGG(CONCAT(problem, N' ', id), N'; ')
    )
    FROM @violations;
    THROW 51000, @msg, 1;
END;
GO

/* ============================================================
   Step 1. Display + grantability columns
   ============================================================ */
-- module_code: groups grid rows (CRM, WF, EMAIL ...), uppercase like nav.menu_module.code.
-- Temporary default so existing rows get 'GENERAL'; then drop it so new rows must state a module.
IF COL_LENGTH('auth.permission', 'module_code') IS NULL
BEGIN
    ALTER TABLE auth.permission
        ADD module_code varchar(50) NOT NULL
            CONSTRAINT DF_permission_module_code_tmp DEFAULT ('GENERAL');
    ALTER TABLE auth.permission DROP CONSTRAINT DF_permission_module_code_tmp;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_permission_module_code_upper'
      AND parent_object_id = OBJECT_ID('auth.permission')
)
    ALTER TABLE auth.permission WITH CHECK
        ADD CONSTRAINT CK_permission_module_code_upper
        CHECK (
            LEN(module_code) > 0
            AND module_code = UPPER(module_code) COLLATE Latin1_General_CS_AS
        );
GO

-- resource_name: row label in the grid ("Lead", "Inbox")
IF COL_LENGTH('auth.permission', 'resource_name') IS NULL
    ALTER TABLE auth.permission ADD resource_name nvarchar(100) NULL;
GO

UPDATE p
SET resource_name = LEFT(COALESCE(ts.display_name, ns.name, p.resource_code), 100)
FROM auth.permission p
LEFT JOIN txn.screen ts
    ON p.resource_type = 'screen'
   AND ts.screen_key = p.resource_code
   AND ts.is_deleted = 0
LEFT JOIN nav.screen ns
    ON p.resource_type = 'menu'
   AND ns.code = p.resource_code
   AND ns.is_deleted = 0
WHERE p.resource_name IS NULL;
GO

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('auth.permission')
      AND name = 'resource_name'
      AND is_nullable = 1
)
    ALTER TABLE auth.permission ALTER COLUMN resource_name nvarchar(100) NOT NULL;
GO

-- sort_order: row order within a module
IF COL_LENGTH('auth.permission', 'sort_order') IS NULL
    ALTER TABLE auth.permission
        ADD sort_order int NOT NULL CONSTRAINT DF_permission_sort_order DEFAULT (0);
GO

-- is_tenant_grantable: 0 = platform-only, hidden from tenant admins
IF COL_LENGTH('auth.permission', 'is_tenant_grantable') IS NULL
    ALTER TABLE auth.permission
        ADD is_tenant_grantable bit NOT NULL
            CONSTRAINT DF_permission_is_tenant_grantable DEFAULT (1);
GO

-- System-scope rows can never be tenant-grantable. Fix existing rows first.
UPDATE auth.permission
SET is_tenant_grantable = 0
WHERE user_scope = 'system' AND is_tenant_grantable = 1;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_permission_system_not_grantable'
      AND parent_object_id = OBJECT_ID('auth.permission')
)
    ALTER TABLE auth.permission WITH CHECK
        ADD CONSTRAINT CK_permission_system_not_grantable
        CHECK (user_scope <> 'system' OR is_tenant_grantable = 0);
GO

/* ============================================================
   Step 2. Unique (user_scope, code); admin-grid index
   ============================================================ */
IF EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('auth.permission')
      AND name = 'UQ_permission_code'
)
    DROP INDEX UQ_permission_code ON auth.permission;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('auth.permission')
      AND name = 'UQ_permission_scope_code'
)
    CREATE UNIQUE NONCLUSTERED INDEX UQ_permission_scope_code
        ON auth.permission (user_scope, code)
        WHERE is_deleted = 0;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('auth.permission')
      AND name = 'IX_permission_admin_grid'
)
    CREATE NONCLUSTERED INDEX IX_permission_admin_grid
        ON auth.permission (user_scope, module_code, sort_order)
        INCLUDE (resource_type, resource_code, action, resource_name, is_tenant_grantable, is_active)
        WHERE is_deleted = 0;
GO
