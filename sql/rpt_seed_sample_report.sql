-- ============================================================================
-- rpt sample reports — five system-wide reports over mtf tables
-- ============================================================================
-- Run in SSMS as deevo_ddl AFTER rpt_schema_v5.sql. Safe to re-run:
--   * procs use CREATE OR ALTER
--   * catalog metadata for the five report keys below is DELETED and re-inserted in one
--     transaction, including any saved views on those reports. This hard delete is a seed
--     exception to the soft-delete rule — the rows are curated metadata owned by this script.
--
--   report_key                    proc                                  notes
--   ----------------------------  ------------------------------------  ----------------------
--   tenant_account_list           rpt.usp_tenant_account_list           detail list
--   tenant_account_summary        rpt.usp_tenant_account_summary        aggregated by type/status
--   tenant_account_address_list   rpt.usp_tenant_account_address_list   join + text/bool criteria
--   tenant_user_list              rpt.usp_tenant_user_list              tenant staff users
--   portal_user_list              rpt.usp_portal_user_list              account portal users
--
-- IDs use the 01JRPTMTF prefix so they never collide with reports seeded by other apps
-- (e.g. DeevoFlow's crm_deal_pipeline / sales_invoice_summary).
--
-- Proc contracts (full spec: prompts/rpt/REPORT_API_PROMPT.md, "Stored procedure contract"):
--   Report proc: (@CriteriaJson nvarchar(max), @MaxRows int)
--     * criteria absent from @CriteriaJson mean "no filter"
--     * final SELECT uses TOP (@MaxRows + 1) so the API can detect truncation
--     * result-set column names exactly match the report's active report_column rows
--   Lookup proc: (@SearchText nvarchar(200) = NULL, @Values nvarchar(max) = NULL,
--                 @MaxRows int = 50)
--     * @Values is a JSON array of value strings; TOP (@MaxRows + 1)
--     * returns exactly two columns: [value] (always a string) and [label]
--   Both read the tenant from SESSION_CONTEXT(N'tenant_id'), set by the API per request.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Runtime grants for deevo_app: catalog reads, proc execution, saved-view writes
-- ----------------------------------------------------------------------------
GRANT SELECT  ON SCHEMA::rpt TO deevo_app;
GRANT EXECUTE ON SCHEMA::rpt TO deevo_app;
GRANT INSERT, UPDATE ON rpt.report_saved_view TO deevo_app;
GO

-- ============================================================================
-- Lookup procs
-- ============================================================================
CREATE OR ALTER PROCEDURE rpt.usp_lookup_account_type
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'customer', N'Customer', 1),
        (N'vendor',   N'Vendor',   2),
        (N'employee', N'Employee', 3)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
END
GO

CREATE OR ALTER PROCEDURE rpt.usp_lookup_account_status
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    SELECT TOP (@MaxRows + 1) s.value, s.label
    FROM (
        SELECT DISTINCT
            CONVERT(nvarchar(20), a.status) AS value,
            CONVERT(nvarchar(20), a.status) AS label
        FROM tenant.tenant_account AS a
        WHERE a.tenant_id = @TenantId
          AND a.is_deleted = 0
    ) AS s
    WHERE (@SearchText IS NULL OR s.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR s.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY s.label;
END
GO

-- value = account id, label = "CODE - Name"; searchable by code or name
CREATE OR ALTER PROCEDURE rpt.usp_lookup_account
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    SELECT TOP (@MaxRows + 1)
        CONVERT(nvarchar(26), a.id)                      AS value,
        CONCAT(a.account_code, N' - ', a.name)           AS label
    FROM tenant.tenant_account AS a
    WHERE a.tenant_id = @TenantId
      AND a.is_deleted = 0
      AND (@SearchText IS NULL
           OR a.name LIKE N'%' + @SearchText + N'%'
           OR a.account_code LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR a.id IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY a.name;
END
GO

CREATE OR ALTER PROCEDURE rpt.usp_lookup_address_type
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    SELECT TOP (@MaxRows + 1) s.value, s.label
    FROM (
        SELECT DISTINCT ad.address_type AS value, ad.address_type AS label
        FROM tenant.tenant_account_address AS ad
        WHERE ad.tenant_id = @TenantId
          AND ad.is_deleted = 0
    ) AS s
    WHERE (@SearchText IS NULL OR s.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR s.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY s.label;
END
GO

-- values mirror CK_tenant_user_role
CREATE OR ALTER PROCEDURE rpt.usp_lookup_tenant_user_role
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'owner',  N'Owner',  1),
        (N'admin',  N'Admin',  2),
        (N'member', N'Member', 3),
        (N'viewer', N'Viewer', 4)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
END
GO

CREATE OR ALTER PROCEDURE rpt.usp_lookup_portal_user_role
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    SELECT TOP (@MaxRows + 1) s.value, s.label
    FROM (
        SELECT DISTINCT
            CONVERT(nvarchar(20), tau.role) AS value,
            CONVERT(nvarchar(20), tau.role) AS label
        FROM auth.tenant_account_user AS tau
        WHERE tau.tenant_id = @TenantId
          AND tau.is_deleted = 0
    ) AS s
    WHERE (@SearchText IS NULL OR s.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR s.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY s.label;
END
GO

-- ============================================================================
-- Report procs
-- ============================================================================

-- 1. tenant_account_list
-- {"account_type": ["customer","vendor"], "status": "active",
--  "created_date": {"from": "2026-01-01", "to": "2026-12-31"}}
CREATE OR ALTER PROCEDURE rpt.usp_tenant_account_list
    @CriteriaJson nvarchar(max),
    @MaxRows      int
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    IF @CriteriaJson IS NULL OR ISJSON(@CriteriaJson) = 0
        SET @CriteriaJson = N'{}';

    DECLARE @Status      varchar(20) = JSON_VALUE(@CriteriaJson, '$.status');
    DECLARE @CreatedFrom date        = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.created_date.from') AS date);
    DECLARE @CreatedTo   date        = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.created_date.to')   AS date);

    DECLARE @AccountTypes TABLE (account_type nvarchar(50) PRIMARY KEY);
    INSERT INTO @AccountTypes (account_type)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.account_type') AS j
    WHERE j.[value] IS NOT NULL;

    SELECT TOP (@MaxRows + 1)
        a.account_code,
        a.name,
        a.account_type,
        a.status,
        a.email,
        a.phone,
        a.is_active,
        a.created_at
    FROM tenant.tenant_account AS a
    WHERE a.tenant_id = @TenantId
      AND a.is_deleted = 0
      AND (@Status IS NULL OR a.status = @Status)
      AND (@CreatedFrom IS NULL OR a.created_at >= @CreatedFrom)
      AND (@CreatedTo   IS NULL OR a.created_at <  DATEADD(day, 1, @CreatedTo))
      AND (NOT EXISTS (SELECT 1 FROM @AccountTypes)
           OR a.account_type IN (SELECT account_type FROM @AccountTypes))
    ORDER BY a.name;
END
GO

-- 2. tenant_account_summary — one row per (account_type, status)
-- {"account_type": ["customer"], "created_date": {"from": "2026-01-01", "to": "2026-12-31"}}
CREATE OR ALTER PROCEDURE rpt.usp_tenant_account_summary
    @CriteriaJson nvarchar(max),
    @MaxRows      int
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    IF @CriteriaJson IS NULL OR ISJSON(@CriteriaJson) = 0
        SET @CriteriaJson = N'{}';

    DECLARE @CreatedFrom date = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.created_date.from') AS date);
    DECLARE @CreatedTo   date = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.created_date.to')   AS date);

    DECLARE @AccountTypes TABLE (account_type nvarchar(50) PRIMARY KEY);
    INSERT INTO @AccountTypes (account_type)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.account_type') AS j
    WHERE j.[value] IS NOT NULL;

    SELECT TOP (@MaxRows + 1)
        a.account_type,
        a.status,
        COUNT(*)                                       AS account_count,
        SUM(CASE WHEN a.is_active = 1 THEN 1 ELSE 0 END) AS active_count,
        SUM(CASE WHEN a.is_active = 0 THEN 1 ELSE 0 END) AS inactive_count,
        MIN(a.created_at)                              AS first_created_at,
        MAX(a.created_at)                              AS last_created_at
    FROM tenant.tenant_account AS a
    WHERE a.tenant_id = @TenantId
      AND a.is_deleted = 0
      AND (@CreatedFrom IS NULL OR a.created_at >= @CreatedFrom)
      AND (@CreatedTo   IS NULL OR a.created_at <  DATEADD(day, 1, @CreatedTo))
      AND (NOT EXISTS (SELECT 1 FROM @AccountTypes)
           OR a.account_type IN (SELECT account_type FROM @AccountTypes))
    GROUP BY a.account_type, a.status
    ORDER BY a.account_type, a.status;
END
GO

-- 3. tenant_account_address_list
-- {"account_id": "01J...", "address_type": ["billing","shipping"], "city": "Austin",
--  "country": "US", "default_only": true}
CREATE OR ALTER PROCEDURE rpt.usp_tenant_account_address_list
    @CriteriaJson nvarchar(max),
    @MaxRows      int
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    IF @CriteriaJson IS NULL OR ISJSON(@CriteriaJson) = 0
        SET @CriteriaJson = N'{}';

    DECLARE @AccountId   varchar(26)   = JSON_VALUE(@CriteriaJson, '$.account_id');
    DECLARE @City        nvarchar(100) = JSON_VALUE(@CriteriaJson, '$.city');
    DECLARE @Country     varchar(2)    = JSON_VALUE(@CriteriaJson, '$.country');
    DECLARE @DefaultOnly bit           = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.default_only') AS bit);

    DECLARE @AddressTypes TABLE (address_type nvarchar(50) PRIMARY KEY);
    INSERT INTO @AddressTypes (address_type)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.address_type') AS j
    WHERE j.[value] IS NOT NULL;

    SELECT TOP (@MaxRows + 1)
        a.account_code,
        a.name AS account_name,
        a.account_type,
        ad.address_type,
        ad.is_default,
        ad.address_line1,
        ad.address_line2,
        ad.city,
        ad.state,
        ad.postal_code,
        ad.country
    FROM tenant.tenant_account_address AS ad
    JOIN tenant.tenant_account AS a
      ON a.id = ad.account_id
     AND a.tenant_id = ad.tenant_id
    WHERE ad.tenant_id = @TenantId
      AND ad.is_deleted = 0
      AND a.is_deleted = 0
      AND (@AccountId IS NULL OR a.id = @AccountId)
      AND (@City      IS NULL OR ad.city LIKE N'%' + @City + N'%')
      AND (@Country   IS NULL OR ad.country = @Country)
      AND (ISNULL(@DefaultOnly, 0) = 0 OR ad.is_default = 1)
      AND (NOT EXISTS (SELECT 1 FROM @AddressTypes)
           OR ad.address_type IN (SELECT address_type FROM @AddressTypes))
    ORDER BY a.name, ad.address_type;
END
GO

-- 4. tenant_user_list — staff users of the current tenant
-- {"role": ["owner","admin"], "is_active": true,
--  "joined_date": {"from": "2026-01-01", "to": "2026-12-31"}}
CREATE OR ALTER PROCEDURE rpt.usp_tenant_user_list
    @CriteriaJson nvarchar(max),
    @MaxRows      int
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    IF @CriteriaJson IS NULL OR ISJSON(@CriteriaJson) = 0
        SET @CriteriaJson = N'{}';

    DECLARE @IsActive   bit  = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.is_active') AS bit);
    DECLARE @JoinedFrom date = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.joined_date.from') AS date);
    DECLARE @JoinedTo   date = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.joined_date.to')   AS date);

    DECLARE @Roles TABLE (role varchar(50) PRIMARY KEY);
    INSERT INTO @Roles (role)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.role') AS j
    WHERE j.[value] IS NOT NULL;

    SELECT TOP (@MaxRows + 1)
        u.email,
        u.first_name,
        u.last_name,
        tu.role,
        tu.is_active,
        u.mfa_enabled,
        tu.joined_at,
        u.last_login_at
    FROM auth.tenant_user AS tu
    JOIN auth.app_user AS u
      ON u.id = tu.user_id
    WHERE tu.tenant_id = @TenantId
      AND tu.is_deleted = 0
      AND u.is_deleted = 0
      AND (@IsActive   IS NULL OR tu.is_active = @IsActive)
      AND (@JoinedFrom IS NULL OR tu.joined_at >= @JoinedFrom)
      AND (@JoinedTo   IS NULL OR tu.joined_at <  DATEADD(day, 1, @JoinedTo))
      AND (NOT EXISTS (SELECT 1 FROM @Roles)
           OR tu.role IN (SELECT role FROM @Roles))
    ORDER BY u.last_name, u.first_name, u.email;
END
GO

-- 5. portal_user_list — portal (tenant_account) users across the tenant's accounts
-- {"account_id": "01J...", "role": "admin", "is_active": true}
CREATE OR ALTER PROCEDURE rpt.usp_portal_user_list
    @CriteriaJson nvarchar(max),
    @MaxRows      int
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    IF @CriteriaJson IS NULL OR ISJSON(@CriteriaJson) = 0
        SET @CriteriaJson = N'{}';

    DECLARE @AccountId varchar(26) = JSON_VALUE(@CriteriaJson, '$.account_id');
    DECLARE @Role      varchar(20) = JSON_VALUE(@CriteriaJson, '$.role');
    DECLARE @IsActive  bit         = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.is_active') AS bit);

    SELECT TOP (@MaxRows + 1)
        a.account_code,
        a.name AS account_name,
        u.email,
        u.first_name,
        u.last_name,
        tau.role,
        tau.is_active,
        tau.joined_at,
        u.last_login_at
    FROM auth.tenant_account_user AS tau
    JOIN auth.app_user AS u
      ON u.id = tau.user_id
    JOIN tenant.tenant_account AS a
      ON a.id = tau.account_id
     AND a.tenant_id = tau.tenant_id
    WHERE tau.tenant_id = @TenantId
      AND tau.is_deleted = 0
      AND u.is_deleted = 0
      AND a.is_deleted = 0
      AND (@AccountId IS NULL OR a.id = @AccountId)
      AND (@Role      IS NULL OR tau.role = @Role)
      AND (@IsActive  IS NULL OR tau.is_active = @IsActive)
    ORDER BY a.name, u.email;
END
GO

-- ============================================================================
-- Catalog metadata — delete then insert, all-or-nothing
-- ============================================================================
SET XACT_ABORT ON;
BEGIN TRANSACTION;

DECLARE @SeedReports TABLE (id varchar(26) PRIMARY KEY);
INSERT INTO @SeedReports (id)
SELECT d.id
FROM rpt.report_definition AS d
WHERE d.id LIKE '01JRPTMTF%'
   OR (d.scope_type = 'system'
       AND d.report_key IN ('tenant_account_list', 'tenant_account_summary',
                            'tenant_account_address_list', 'tenant_user_list',
                            'portal_user_list'));

DELETE FROM rpt.report_saved_view WHERE report_id IN (SELECT id FROM @SeedReports);
DELETE FROM rpt.report_criteria   WHERE report_id IN (SELECT id FROM @SeedReports);
DELETE FROM rpt.report_column     WHERE report_id IN (SELECT id FROM @SeedReports);
DELETE FROM rpt.report_definition WHERE id        IN (SELECT id FROM @SeedReports);

DECLARE @R1 varchar(26) = '01JRPTMTFDF000000000000001';  -- tenant_account_list
DECLARE @R2 varchar(26) = '01JRPTMTFDF000000000000002';  -- tenant_account_summary
DECLARE @R3 varchar(26) = '01JRPTMTFDF000000000000003';  -- tenant_account_address_list
DECLARE @R4 varchar(26) = '01JRPTMTFDF000000000000004';  -- tenant_user_list
DECLARE @R5 varchar(26) = '01JRPTMTFDF000000000000005';  -- portal_user_list

-- ----------------------------------------------------------------------------
-- report_definition
-- ----------------------------------------------------------------------------
INSERT INTO rpt.report_definition
    (id, tenant_id, scope_type, report_key, display_name, proc_name, description, default_max_rows)
VALUES
    (@R1, NULL, 'system', 'tenant_account_list',         N'Account List',
     'rpt.usp_tenant_account_list',
     N'All accounts for the current tenant, filterable by type, status, and created date.', 20000),
    (@R2, NULL, 'system', 'tenant_account_summary',      N'Account Summary',
     'rpt.usp_tenant_account_summary',
     N'Account counts by type and status, with active/inactive totals.',                    1000),
    (@R3, NULL, 'system', 'tenant_account_address_list', N'Account Addresses',
     'rpt.usp_tenant_account_address_list',
     N'Addresses for all accounts, filterable by account, address type, city, and country.', 20000),
    (@R4, NULL, 'system', 'tenant_user_list',            N'Staff Users',
     'rpt.usp_tenant_user_list',
     N'Staff users of the current tenant with role, status, and last login.',               5000),
    (@R5, NULL, 'system', 'portal_user_list',            N'Portal Users',
     'rpt.usp_portal_user_list',
     N'Portal users for each account with role, status, and last login.',                   20000);

-- ----------------------------------------------------------------------------
-- report_column
-- ----------------------------------------------------------------------------
INSERT INTO rpt.report_column
    (id, report_id, column_name, display_name, data_type, display_order,
     is_displayable, is_default_visible, is_sortable, is_groupable, is_filterable,
     is_aggregatable, default_aggregate_type, display_format, default_width)
VALUES
    -- 1. tenant_account_list
    ('01JRPTMTFCM000000000000101', @R1, 'account_code',     N'Code',          'string',   10, 1, 1, 1, 0, 1, 0, NULL,    NULL,         120),
    ('01JRPTMTFCM000000000000102', @R1, 'name',             N'Name',          'string',   20, 1, 1, 1, 0, 1, 0, NULL,    NULL,         240),
    ('01JRPTMTFCM000000000000103', @R1, 'account_type',     N'Type',          'string',   30, 1, 1, 1, 1, 1, 1, 'count', NULL,         120),
    ('01JRPTMTFCM000000000000104', @R1, 'status',           N'Status',        'string',   40, 1, 1, 1, 1, 1, 0, NULL,    NULL,         110),
    ('01JRPTMTFCM000000000000105', @R1, 'email',            N'Email',         'string',   50, 1, 1, 1, 0, 1, 0, NULL,    NULL,         220),
    ('01JRPTMTFCM000000000000106', @R1, 'phone',            N'Phone',         'string',   60, 1, 0, 1, 0, 1, 0, NULL,    NULL,         140),
    ('01JRPTMTFCM000000000000107', @R1, 'is_active',        N'Active',        'bool',     70, 1, 0, 1, 1, 1, 0, NULL,    NULL,          90),
    ('01JRPTMTFCM000000000000108', @R1, 'created_at',       N'Created',       'datetime', 80, 1, 1, 1, 0, 1, 0, NULL,    'MM/dd/yyyy', 130),

    -- 2. tenant_account_summary
    ('01JRPTMTFCM000000000000201', @R2, 'account_type',     N'Type',          'string',   10, 1, 1, 1, 1, 1, 0, NULL,    NULL,         140),
    ('01JRPTMTFCM000000000000202', @R2, 'status',           N'Status',        'string',   20, 1, 1, 1, 1, 1, 0, NULL,    NULL,         120),
    ('01JRPTMTFCM000000000000203', @R2, 'account_count',    N'Accounts',      'int',      30, 1, 1, 1, 0, 1, 1, 'sum',   NULL,         110),
    ('01JRPTMTFCM000000000000204', @R2, 'active_count',     N'Active',        'int',      40, 1, 1, 1, 0, 1, 1, 'sum',   NULL,         110),
    ('01JRPTMTFCM000000000000205', @R2, 'inactive_count',   N'Inactive',      'int',      50, 1, 1, 1, 0, 1, 1, 'sum',   NULL,         110),
    ('01JRPTMTFCM000000000000206', @R2, 'first_created_at', N'First Created', 'datetime', 60, 1, 0, 1, 0, 1, 1, 'min',   'MM/dd/yyyy', 130),
    ('01JRPTMTFCM000000000000207', @R2, 'last_created_at',  N'Last Created',  'datetime', 70, 1, 1, 1, 0, 1, 1, 'max',   'MM/dd/yyyy', 130),

    -- 3. tenant_account_address_list
    ('01JRPTMTFCM000000000000301', @R3, 'account_code',     N'Code',          'string',   10, 1, 1, 1, 0, 1, 0, NULL,    NULL,         120),
    ('01JRPTMTFCM000000000000302', @R3, 'account_name',     N'Account',       'string',   20, 1, 1, 1, 1, 1, 0, NULL,    NULL,         220),
    ('01JRPTMTFCM000000000000303', @R3, 'account_type',     N'Account Type',  'string',   30, 1, 0, 1, 1, 1, 0, NULL,    NULL,         120),
    ('01JRPTMTFCM000000000000304', @R3, 'address_type',     N'Address Type',  'string',   40, 1, 1, 1, 1, 1, 1, 'count', NULL,         120),
    ('01JRPTMTFCM000000000000305', @R3, 'is_default',       N'Default',       'bool',     50, 1, 1, 1, 0, 1, 0, NULL,    NULL,          90),
    ('01JRPTMTFCM000000000000306', @R3, 'address_line1',    N'Address 1',     'string',   60, 1, 1, 0, 0, 1, 0, NULL,    NULL,         220),
    ('01JRPTMTFCM000000000000307', @R3, 'address_line2',    N'Address 2',     'string',   70, 1, 0, 0, 0, 1, 0, NULL,    NULL,         160),
    ('01JRPTMTFCM000000000000308', @R3, 'city',             N'City',          'string',   80, 1, 1, 1, 1, 1, 0, NULL,    NULL,         140),
    ('01JRPTMTFCM000000000000309', @R3, 'state',            N'State',         'string',   90, 1, 1, 1, 1, 1, 0, NULL,    NULL,         100),
    ('01JRPTMTFCM000000000000310', @R3, 'postal_code',      N'Postal Code',   'string',  100, 1, 1, 1, 0, 1, 0, NULL,    NULL,         110),
    ('01JRPTMTFCM000000000000311', @R3, 'country',          N'Country',       'string',  110, 1, 1, 1, 1, 1, 0, NULL,    NULL,          90),

    -- 4. tenant_user_list
    ('01JRPTMTFCM000000000000401', @R4, 'email',            N'Email',         'string',   10, 1, 1, 1, 0, 1, 0, NULL,    NULL,         240),
    ('01JRPTMTFCM000000000000402', @R4, 'first_name',       N'First Name',    'string',   20, 1, 1, 1, 0, 1, 0, NULL,    NULL,         140),
    ('01JRPTMTFCM000000000000403', @R4, 'last_name',        N'Last Name',     'string',   30, 1, 1, 1, 0, 1, 0, NULL,    NULL,         140),
    ('01JRPTMTFCM000000000000404', @R4, 'role',             N'Role',          'string',   40, 1, 1, 1, 1, 1, 1, 'count', NULL,         110),
    ('01JRPTMTFCM000000000000405', @R4, 'is_active',        N'Active',        'bool',     50, 1, 1, 1, 1, 1, 0, NULL,    NULL,          90),
    ('01JRPTMTFCM000000000000406', @R4, 'mfa_enabled',      N'MFA',           'bool',     60, 1, 0, 1, 1, 1, 0, NULL,    NULL,          80),
    ('01JRPTMTFCM000000000000407', @R4, 'joined_at',        N'Joined',        'datetime', 70, 1, 1, 1, 0, 1, 0, NULL,    'MM/dd/yyyy', 130),
    ('01JRPTMTFCM000000000000408', @R4, 'last_login_at',    N'Last Login',    'datetime', 80, 1, 1, 1, 0, 1, 1, 'max',   'MM/dd/yyyy', 130),

    -- 5. portal_user_list
    ('01JRPTMTFCM000000000000501', @R5, 'account_code',     N'Code',          'string',   10, 1, 1, 1, 0, 1, 0, NULL,    NULL,         120),
    ('01JRPTMTFCM000000000000502', @R5, 'account_name',     N'Account',       'string',   20, 1, 1, 1, 1, 1, 1, 'count', NULL,         220),
    ('01JRPTMTFCM000000000000503', @R5, 'email',            N'Email',         'string',   30, 1, 1, 1, 0, 1, 0, NULL,    NULL,         240),
    ('01JRPTMTFCM000000000000504', @R5, 'first_name',       N'First Name',    'string',   40, 1, 1, 1, 0, 1, 0, NULL,    NULL,         140),
    ('01JRPTMTFCM000000000000505', @R5, 'last_name',        N'Last Name',     'string',   50, 1, 1, 1, 0, 1, 0, NULL,    NULL,         140),
    ('01JRPTMTFCM000000000000506', @R5, 'role',             N'Role',          'string',   60, 1, 1, 1, 1, 1, 0, NULL,    NULL,         100),
    ('01JRPTMTFCM000000000000507', @R5, 'is_active',        N'Active',        'bool',     70, 1, 1, 1, 1, 1, 0, NULL,    NULL,          90),
    ('01JRPTMTFCM000000000000508', @R5, 'joined_at',        N'Joined',        'datetime', 80, 1, 0, 1, 0, 1, 0, NULL,    'MM/dd/yyyy', 130),
    ('01JRPTMTFCM000000000000509', @R5, 'last_login_at',    N'Last Login',    'datetime', 90, 1, 1, 1, 0, 1, 1, 'max',   'MM/dd/yyyy', 130);

-- ----------------------------------------------------------------------------
-- report_criteria
-- ----------------------------------------------------------------------------
INSERT INTO rpt.report_criteria
    (id, report_id, criteria_key, display_name, data_type, control_type,
     lookup_proc, default_value, is_required, display_order)
VALUES
    -- 1. tenant_account_list
    ('01JRPTMTFCR000000000000101', @R1, 'account_type', N'Account Type', 'string', 'multiselect',
     'rpt.usp_lookup_account_type',      NULL,      0, 10),
    ('01JRPTMTFCR000000000000102', @R1, 'status',       N'Status',       'string', 'dropdown',
     'rpt.usp_lookup_account_status',    N'active', 0, 20),
    ('01JRPTMTFCR000000000000103', @R1, 'created_date', N'Created Date', 'date',   'daterange',
     NULL,                               NULL,      0, 30),

    -- 2. tenant_account_summary
    ('01JRPTMTFCR000000000000201', @R2, 'account_type', N'Account Type', 'string', 'multiselect',
     'rpt.usp_lookup_account_type',      NULL,      0, 10),
    ('01JRPTMTFCR000000000000202', @R2, 'created_date', N'Created Date', 'date',   'daterange',
     NULL,                               NULL,      0, 20),

    -- 3. tenant_account_address_list
    ('01JRPTMTFCR000000000000301', @R3, 'account_id',   N'Account',      'string', 'dropdown',
     'rpt.usp_lookup_account',           NULL,      0, 10),
    ('01JRPTMTFCR000000000000302', @R3, 'address_type', N'Address Type', 'string', 'multiselect',
     'rpt.usp_lookup_address_type',      NULL,      0, 20),
    ('01JRPTMTFCR000000000000303', @R3, 'city',         N'City',         'string', 'text',
     NULL,                               NULL,      0, 30),
    ('01JRPTMTFCR000000000000304', @R3, 'country',      N'Country',      'string', 'text',
     NULL,                               NULL,      0, 40),
    ('01JRPTMTFCR000000000000305', @R3, 'default_only', N'Default Only', 'bool',   'bool',
     NULL,                               N'false',  0, 50),

    -- 4. tenant_user_list
    ('01JRPTMTFCR000000000000401', @R4, 'role',         N'Role',         'string', 'multiselect',
     'rpt.usp_lookup_tenant_user_role',  NULL,      0, 10),
    ('01JRPTMTFCR000000000000402', @R4, 'is_active',    N'Active',       'bool',   'bool',
     NULL,                               N'true',   0, 20),
    ('01JRPTMTFCR000000000000403', @R4, 'joined_date',  N'Joined Date',  'date',   'daterange',
     NULL,                               NULL,      0, 30),

    -- 5. portal_user_list
    ('01JRPTMTFCR000000000000501', @R5, 'account_id',   N'Account',      'string', 'dropdown',
     'rpt.usp_lookup_account',           NULL,      0, 10),
    ('01JRPTMTFCR000000000000502', @R5, 'role',         N'Role',         'string', 'dropdown',
     'rpt.usp_lookup_portal_user_role',  NULL,      0, 20),
    ('01JRPTMTFCR000000000000503', @R5, 'is_active',    N'Active',       'bool',   'bool',
     NULL,                               N'true',   0, 30);

COMMIT TRANSACTION;
GO
