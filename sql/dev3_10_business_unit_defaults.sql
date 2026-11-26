/*
    dev3_10_business_unit_defaults.sql
    Database: deevo_app_dev3
    Requires: tenant.tenant (data loaded), tenant.business_unit (created)
    Design:   sql/business_unit_database_design.md (§3, §6, §8 step 3.2)

    Creates the default business units for every tenant:
      1. ROOT  bu_type = 'root',  code = 'COMPANY', name = tenant name, no parent
      2. MAIN  bu_type = 'store', code = 'MAIN',    name = 'Main Store', parent = ROOT
         (only when the tenant has no live non-root unit yet)

    Address and timezone are copied from tenant.tenant to both units; currency is
    left NULL (= use the tenant default).

    IDs are deterministic (prefix + SHA-256 of the tenant id, hex), the same
    pattern as auth_rbac_backfill_v3.sql. Rerunning produces the same IDs, and
    later migration scripts can compute a tenant's ROOT / MAIN id without a lookup:
        ROOT = LEFT('01JBXR' + hex(SHA2_256(N'bu-root|' + tenant_id)), 26)
        MAIN = LEFT('01JBXM' + hex(SHA2_256(N'bu-main|' + tenant_id)), 26)

    Units are created for soft-deleted tenants too: every tenant table needs a
    NOT NULL business_unit_id, including rows that belong to deleted tenants.

    Apply as the DDL/owner login. Safe to rerun.
*/
USE [deevo_app_dev3];
GO

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

BEGIN TRANSACTION;

/* -------------------------------------------------------------------------
   1. ROOT unit — one per tenant
   ------------------------------------------------------------------------- */
INSERT INTO tenant.business_unit (
    id, tenant_id, parent_id, bu_type, code, name,
    address_line1, address_line2, city, state, postal_code, country,
    timezone, currency, sort_order
)
SELECT
    LEFT('01JBXR' + CONVERT(varchar(64), HASHBYTES('SHA2_256', CONCAT(N'bu-root|', t.id)), 2), 26),
    t.id,
    NULL,
    'root',
    'COMPANY',
    t.name,
    t.address_line1, t.address_line2, t.city, t.state, t.postal_code, t.country,
    t.timezone,
    NULL,
    0
FROM tenant.tenant AS t
WHERE NOT EXISTS (
        SELECT 1
        FROM tenant.business_unit AS bu
        WHERE bu.tenant_id = t.id
          AND bu.bu_type = 'root'
          AND bu.is_deleted = 0
    );

PRINT CONCAT('ROOT units created: ', @@ROWCOUNT);

/* -------------------------------------------------------------------------
   2. MAIN store — only for tenants that have no live non-root unit
   ------------------------------------------------------------------------- */
INSERT INTO tenant.business_unit (
    id, tenant_id, parent_id, bu_type, code, name,
    address_line1, address_line2, city, state, postal_code, country,
    timezone, currency, sort_order
)
SELECT
    LEFT('01JBXM' + CONVERT(varchar(64), HASHBYTES('SHA2_256', CONCAT(N'bu-main|', t.id)), 2), 26),
    t.id,
    r.id,
    'store',
    'MAIN',
    N'Main Store',
    t.address_line1, t.address_line2, t.city, t.state, t.postal_code, t.country,
    t.timezone,
    NULL,
    1
FROM tenant.tenant AS t
JOIN tenant.business_unit AS r
    ON r.tenant_id = t.id
   AND r.bu_type = 'root'
   AND r.is_deleted = 0
WHERE NOT EXISTS (
        SELECT 1
        FROM tenant.business_unit AS bu
        WHERE bu.tenant_id = t.id
          AND bu.bu_type <> 'root'
          AND bu.is_deleted = 0
    );

PRINT CONCAT('MAIN stores created: ', @@ROWCOUNT);

COMMIT TRANSACTION;
GO

/* -------------------------------------------------------------------------
   3. Checks — both queries must return no rows
   ------------------------------------------------------------------------- */
-- Tenants without exactly one live ROOT
SELECT t.id, t.name, COUNT(bu.id) AS root_count
FROM tenant.tenant AS t
LEFT JOIN tenant.business_unit AS bu
    ON bu.tenant_id = t.id AND bu.bu_type = 'root' AND bu.is_deleted = 0
GROUP BY t.id, t.name
HAVING COUNT(bu.id) <> 1;

-- Tenants without at least one live store under the ROOT
SELECT t.id, t.name
FROM tenant.tenant AS t
WHERE NOT EXISTS (
        SELECT 1
        FROM tenant.business_unit AS bu
        WHERE bu.tenant_id = t.id
          AND bu.bu_type <> 'root'
          AND bu.is_deleted = 0
    );

-- Overview
SELECT t.name AS tenant, bu.bu_type, bu.code, bu.name, bu.id, bu.parent_id
FROM tenant.business_unit AS bu
JOIN tenant.tenant AS t ON t.id = bu.tenant_id
ORDER BY t.name, bu.sort_order;
GO
