/*
    rbac_fix_03_screens_flag.sql
    Database: deevo_app_dev2
    Requires: tenant.tenant_setting, auth_rbac_backfill_v3.sql (user_role)

    Step 5 of tenant Role Admin: per-tenant fail-closed screen RBAC.

    Screen gates no longer infer RBAC from catalog + any user_role.
    tenant.tenant_setting key rbac.screens = 'on' is the switch.
    When it is on, require_screen_permission uses RBAC only
    (empty grants deny). When it is missing, fall back to
    txn.screen_permission. The switch is one-way: it cannot be
    turned off, deactivated, soft-deleted, or hard-deleted.

    Apply AFTER rbac_fix_02_permission_catalog.sql, as deevo.
    Safe to rerun.

    Step 0  THROW 51030 if live (tenant_id, [key]) duplicates exist
            (the new unique index would fail).
    Step 1  UQ_tenant_setting_tenant_key (tenant_id, [key])
            WHERE is_deleted = 0.
    Step 2  TR_tenant_setting_rbac_screens_one_way.
    Step 3  Insert rbac.screens = 'on' for every live tenant
            that does not already have the row.

    Error numbers: 51030 (existing duplicates / hard delete),
    51031 (insert not on), 51032 (turn off).
    51000–51010 are fix_01; 51020 is the tenant catalog seed.
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
IF EXISTS (
    SELECT 1
    FROM tenant.tenant_setting
    WHERE is_deleted = 0
    GROUP BY tenant_id, [key]
    HAVING COUNT(*) > 1
)
    THROW 51030, N'rbac_fix_03_screens_flag: duplicate live (tenant_id, key) in tenant.tenant_setting. Fix them, then rerun.', 1;
GO

/* ============================================================
   Step 1. One live setting per (tenant, key)
   ============================================================ */
-- Live DB already has UX_tenant_setting_tenant_key (same filter).
-- Keep that name; only create UQ_ if neither unique index exists.
IF EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('tenant.tenant_setting')
      AND name = 'UQ_tenant_setting_tenant_key'
)
AND EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('tenant.tenant_setting')
      AND name = 'UX_tenant_setting_tenant_key'
)
    DROP INDEX UQ_tenant_setting_tenant_key ON tenant.tenant_setting;
GO
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('tenant.tenant_setting')
      AND name IN ('UQ_tenant_setting_tenant_key', 'UX_tenant_setting_tenant_key')
)
    CREATE UNIQUE NONCLUSTERED INDEX UQ_tenant_setting_tenant_key
        ON tenant.tenant_setting (tenant_id, [key])
        WHERE is_deleted = 0;
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

/* ============================================================
   Step 3. Fail-close live tenants
   ============================================================ */
INSERT INTO tenant.tenant_setting (id, tenant_id, [key], [value], is_active, is_deleted)
SELECT
    LEFT('01JRACSTG' + CONVERT(varchar(64), HASHBYTES(
        'SHA2_256', CONCAT(N'rbac.screens|', t.id)), 2), 26),
    t.id,
    'rbac.screens',
    N'on',
    1,
    0
FROM tenant.tenant AS t
WHERE t.is_deleted = 0
  AND NOT EXISTS (
        SELECT 1
        FROM tenant.tenant_setting AS s
        WHERE s.tenant_id = t.id
          AND s.[key] = 'rbac.screens'
          AND s.is_deleted = 0
    );
GO
