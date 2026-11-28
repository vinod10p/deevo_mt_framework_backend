/*
    dev3_12_move_custom_roles_to_store.sql
    Database: deevo_app_dev3
    Requires: dev3_10_business_unit_defaults.sql (every tenant has a root unit and MAIN)
    Decision: BUSINESS_UNIT_BACKEND_PROMPT.md, open item Q1 = option B (Nov 26, 2026)

    The dev2 -> dev3 migration put every user_role row at the tenant's root unit. A role held
    at the root counts in every store, which decision 10 reserves for tenant-wide roles. This
    script moves staff assignments of roles that are NOT tenant-wide to a store:

        target store = the member's default store (tenant_user.default_business_unit_id),
                       else the active store coded MAIN

    Untouched: tenant-wide roles (platform tenant_admin), portal (tenant_account) rows, which
    always sit at the root, system rows, and rows already at a store.

    If the user already holds the same role at the target store (assigned since step 8), the
    root copy is soft-deleted instead of moved (the unique key allows one live row per store).

    Every change is logged in auth.user_role_store_move_log, so it can be undone (see the end
    of this file). Rows with no target store are left alone and listed in the final report.

    Apply as the DDL/owner login. Safe to rerun: a second run finds nothing to move.
*/
USE [deevo_app_dev3];
GO

IF OBJECT_ID(N'auth.user_role_store_move_log', N'U') IS NULL
BEGIN
    CREATE TABLE auth.user_role_store_move_log (
        user_role_id          varchar(26)  NOT NULL CONSTRAINT PK_user_role_store_move_log PRIMARY KEY,
        tenant_id             varchar(26)  NOT NULL,
        user_id               varchar(26)  NOT NULL,
        role_id               varchar(26)  NOT NULL,
        from_business_unit_id varchar(26)  NOT NULL,
        to_business_unit_id   varchar(26)  NOT NULL,
        action                varchar(10)  NOT NULL
            CONSTRAINT CK_user_role_store_move_log_action CHECK (action IN ('moved', 'retired')),
        moved_at              datetime2(3) NOT NULL
            CONSTRAINT DF_user_role_store_move_log_moved_at DEFAULT SYSUTCDATETIME()
    );
END;
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @system_user varchar(26) = '01HYSTEM00000000000000000';
DECLARE @now datetime2(3) = SYSUTCDATETIME();

BEGIN TRANSACTION;

/* 1. Root-held staff assignments of roles that are not tenant-wide, with their target store. */
SELECT
    ur.id               AS user_role_id,
    ur.tenant_id,
    ur.user_id,
    ur.role_id,
    ur.business_unit_id AS from_business_unit_id,
    COALESCE(default_store.id, main_store.id) AS to_business_unit_id
INTO #candidates
FROM auth.user_role AS ur
JOIN auth.role AS r
    ON r.id = ur.role_id
JOIN tenant.business_unit AS root_unit
    ON root_unit.id = ur.business_unit_id
   AND root_unit.bu_type = 'root'
LEFT JOIN auth.tenant_user AS tu
    ON tu.tenant_id = ur.tenant_id
   AND tu.user_id = ur.user_id
   AND tu.is_deleted = 0
LEFT JOIN tenant.business_unit AS default_store
    ON default_store.id = tu.default_business_unit_id
   AND default_store.tenant_id = ur.tenant_id
   AND default_store.bu_type = 'store'
   AND default_store.is_active = 1
   AND default_store.is_deleted = 0
OUTER APPLY (
    SELECT TOP (1) s.id
    FROM tenant.business_unit AS s
    WHERE s.tenant_id = ur.tenant_id
      AND s.bu_type = 'store'
      AND s.code = 'MAIN'
      AND s.is_active = 1
      AND s.is_deleted = 0
    ORDER BY s.sort_order, s.created_at
) AS main_store
WHERE ur.is_deleted = 0
  AND ur.user_scope = 'tenant'
  AND ur.account_id IS NULL
  AND r.is_tenant_wide = 0;

/* 2. Decide per row: move it, or retire it when the store already has the same role. */
SELECT
    c.*,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM auth.user_role AS held
            WHERE held.tenant_id = c.tenant_id
              AND held.user_id = c.user_id
              AND held.role_id = c.role_id
              AND held.account_id IS NULL
              AND held.business_unit_id = c.to_business_unit_id
              AND held.is_deleted = 0
        ) THEN 'retired'
        ELSE 'moved'
    END AS action
INTO #changes
FROM #candidates AS c
WHERE c.to_business_unit_id IS NOT NULL;

/* 3. Apply. */
UPDATE ur
SET business_unit_id = ch.to_business_unit_id,
    updated_at = @now,
    updated_by = @system_user
FROM auth.user_role AS ur
JOIN #changes AS ch ON ch.user_role_id = ur.id AND ch.action = 'moved';

UPDATE ur
SET is_active = 0,
    is_deleted = 1,
    deleted_at = @now,
    deleted_by = @system_user,
    updated_at = @now,
    updated_by = @system_user
FROM auth.user_role AS ur
JOIN #changes AS ch ON ch.user_role_id = ur.id AND ch.action = 'retired';

INSERT INTO auth.user_role_store_move_log (
    user_role_id, tenant_id, user_id, role_id,
    from_business_unit_id, to_business_unit_id, action, moved_at
)
SELECT user_role_id, tenant_id, user_id, role_id,
       from_business_unit_id, to_business_unit_id, action, @now
FROM #changes;

COMMIT TRANSACTION;

/* 4. Report. */
SELECT action, COUNT(*) AS rows_changed
FROM #changes
GROUP BY action;

SELECT user_role_id, tenant_id, user_id, role_id
FROM #candidates
WHERE to_business_unit_id IS NULL;  -- left at the root: no default store and no active MAIN

DROP TABLE #changes;
DROP TABLE #candidates;
GO

/*
    To undo (puts every logged row back at the root and live again):

    BEGIN TRANSACTION;
    UPDATE ur
    SET business_unit_id = log.from_business_unit_id,
        is_active = 1, is_deleted = 0, deleted_at = NULL, deleted_by = NULL,
        updated_at = SYSUTCDATETIME(), updated_by = '01HYSTEM00000000000000000'
    FROM auth.user_role AS ur
    JOIN auth.user_role_store_move_log AS log ON log.user_role_id = ur.id;
    DELETE FROM auth.user_role_store_move_log;
    COMMIT TRANSACTION;
*/
