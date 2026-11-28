/*
    dev3_11_rpt_procedures.sql
    Database: deevo_app_dev3
    Requires: rpt, auth and tenant tables (created and loaded)

    Copies the report programmability from deevo_app_dev2, unchanged except that
    every CREATE became CREATE OR ALTER:
      * rpt.TR_report_definition_scope_guard - a report's tenant/scope can't change
        while role_report or default_role_report rows grant it
      * 38 rpt.usp_* procedures - report data sources and criteria lookups

    The rpt.usp_crm_* procedures and the CRM lookups read crm.* tables, which are
    not migrated to dev3 yet. SQL Server creates them anyway (deferred name
    resolution); they fail only when run, until the crm schema is migrated.

    Apply as the DDL/owner login. Safe to rerun.
*/
USE [deevo_app_dev3];
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

-- ----------------------------------------------------------------------------
-- 4. Report Procedure: rpt.usp_crm_account_list
-- ----------------------------------------------------------------------------
-- Sample criteria JSON:
-- {
--   "search_text": "Apex",
--   "type": ["customer", "partner"],
--   "group_id": "01J...",
--   "account_owner_id": "01J..."
-- }
-- ----------------------------------------------------------------------------
CREATE OR ALTER PROCEDURE rpt.usp_crm_account_list
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

    DECLARE @SearchText nvarchar(200) = NULLIF(LTRIM(RTRIM(JSON_VALUE(@CriteriaJson, '$.search_text'))), '');
    DECLARE @GroupId    varchar(26)   = NULLIF(JSON_VALUE(@CriteriaJson, '$.group_id'), '');
    DECLARE @OwnerId    varchar(26)   = NULLIF(JSON_VALUE(@CriteriaJson, '$.account_owner_id'), '');

    DECLARE @Types TABLE (account_type varchar(30) PRIMARY KEY);
    INSERT INTO @Types (account_type)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.type') AS j
    WHERE j.[value] IS NOT NULL AND j.[value] <> '';

    SELECT TOP (@MaxRows + 1)
        a.id,
        a.name,
        a.type,
        a.phone,
        a.email,
        a.website,
        a.city,
        a.state,
        a.country,
        LTRIM(RTRIM(CONCAT(u.first_name, ' ', u.last_name))) AS owner_name,
        grp.label                                            AS group_label,
        parent.name                                          AS parent_account_name,
        a.created_at
    FROM crm.account AS a
    LEFT JOIN crm.lookup AS grp
        ON grp.id = a.group_id AND grp.is_deleted = 0
    LEFT JOIN crm.account AS parent
        ON parent.id = a.parent_account_id AND parent.is_deleted = 0
    LEFT JOIN auth.tenant_user AS tu
        ON tu.id = a.account_owner_id AND tu.is_deleted = 0
    LEFT JOIN auth.app_user AS u
        ON u.id = tu.user_id AND u.is_deleted = 0
    WHERE a.tenant_id = @TenantId
      AND a.is_deleted = 0
      AND (@SearchText IS NULL OR (
          a.name LIKE N'%' + @SearchText + N'%'
          OR a.email LIKE N'%' + @SearchText + N'%'
          OR a.phone LIKE N'%' + @SearchText + N'%'
          OR a.city LIKE N'%' + @SearchText + N'%'
      ))
      AND (NOT EXISTS (SELECT 1 FROM @Types) OR a.type IN (SELECT account_type FROM @Types))
      AND (@GroupId IS NULL OR a.group_id = @GroupId)
      AND (@OwnerId IS NULL OR a.account_owner_id = @OwnerId)
    ORDER BY a.created_at DESC;
END
GO

-- ----------------------------------------------------------------------------
-- 2. Report Procedure: rpt.usp_crm_contact_list
-- ----------------------------------------------------------------------------
-- Sample criteria JSON:
-- {
--   "search_text": "Ada",
--   "account_id": "01J..."
-- }
-- ----------------------------------------------------------------------------
CREATE OR ALTER PROCEDURE rpt.usp_crm_contact_list
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

    DECLARE @SearchText nvarchar(200) = NULLIF(LTRIM(RTRIM(JSON_VALUE(@CriteriaJson, '$.search_text'))), '');
    DECLARE @AccountId  varchar(26)   = NULLIF(JSON_VALUE(@CriteriaJson, '$.account_id'), '');

    SELECT TOP (@MaxRows + 1)
        c.id,
        c.first_name,
        c.last_name,
        LTRIM(RTRIM(CONCAT(c.first_name, ' ', c.last_name))) AS full_name,
        c.title,
        c.email,
        c.phone,
        c.mobile,
        c.city,
        c.state,
        c.country,
        a.name AS account_name,
        c.account_id,
        c.created_at
    FROM crm.contact AS c
    INNER JOIN crm.account AS a
        ON a.id = c.account_id AND a.is_deleted = 0
    WHERE c.tenant_id = @TenantId
      AND c.is_deleted = 0
      AND (@SearchText IS NULL OR (
          c.first_name LIKE N'%' + @SearchText + N'%'
          OR c.last_name LIKE N'%' + @SearchText + N'%'
          OR c.email LIKE N'%' + @SearchText + N'%'
          OR c.phone LIKE N'%' + @SearchText + N'%'
          OR a.name LIKE N'%' + @SearchText + N'%'
      ))
      AND (@AccountId IS NULL OR c.account_id = @AccountId)
    ORDER BY c.created_at DESC;
END
GO

-- ============================================================================
-- Report procs (fixed sample data per tenant)
-- ============================================================================

-- 1. crm_deal_pipeline
-- {"stage": ["proposal","negotiation"], "priority": "high", "min_amount": 50000,
--  "close_date": {"from": "2026-10-01", "to": "2026-12-31"}, "is_won_only": true}
CREATE OR ALTER PROCEDURE rpt.usp_crm_deal_pipeline
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

    DECLARE @Priority  varchar(20)   = JSON_VALUE(@CriteriaJson, '$.priority');
    DECLARE @MinAmount decimal(18,2) = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.min_amount') AS decimal(18,2));
    DECLARE @CloseFrom date          = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.close_date.from') AS date);
    DECLARE @CloseTo   date          = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.close_date.to')   AS date);
    DECLARE @IsWonOnly bit           = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.is_won_only') AS bit);

    DECLARE @Stages TABLE (stage nvarchar(50) PRIMARY KEY);
    INSERT INTO @Stages (stage)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.stage') AS j
    WHERE j.[value] IS NOT NULL;

    WITH SampleDeals AS (
        SELECT * FROM (VALUES
            (N'Enterprise ERP Upgrade',        N'Acme Global Corp',     N'Sarah Jenkins', N'proposal',      N'high',   125000.00,  75,  93750.00, CAST('2026-11-15' AS date), CAST(0 AS bit), CAST('2026-08-01 10:15:00' AS datetime2(3))),
            (N'Cloud Migration Phase 2',       N'Vertex Logistics',     N'David Ross',    N'negotiation',   N'urgent', 280000.00,  90, 252000.00, CAST('2026-10-30' AS date), CAST(0 AS bit), CAST('2026-07-12 14:30:00' AS datetime2(3))),
            (N'Annual Support Renewal',        N'BluePeak Financial',   N'Sarah Jenkins', N'closed_won',    N'medium',  45000.00, 100,  45000.00, CAST('2026-09-01' AS date), CAST(1 AS bit), CAST('2026-06-20 09:00:00' AS datetime2(3))),
            (N'Custom API Integration',        N'Nexus Media Group',    N'Elena Rostova', N'qualification', N'medium',  35000.00,  40,  14000.00, CAST('2026-12-05' AS date), CAST(0 AS bit), CAST('2026-09-10 16:45:00' AS datetime2(3))),
            (N'Cybersecurity Audit & Tooling', N'Omega Health Systems', N'David Ross',    N'prospecting',   N'high',    85000.00,  20,  17000.00, CAST('2026-12-20' AS date), CAST(0 AS bit), CAST('2026-09-25 11:20:00' AS datetime2(3))),
            (N'AI Analytics Dashboard',        N'Quantix Capital',      N'Sarah Jenkins', N'closed_won',    N'high',   195000.00, 100, 195000.00, CAST('2026-09-28' AS date), CAST(1 AS bit), CAST('2026-05-18 08:30:00' AS datetime2(3))),
            (N'Legacy Database Modernization', N'SilverLine Transit',   N'Elena Rostova', N'closed_lost',   N'low',     60000.00,   0,      0.00, CAST('2026-08-15' AS date), CAST(0 AS bit), CAST('2026-04-10 13:10:00' AS datetime2(3))),
            (N'Mobile App Dev Pilot',          N'Zenith Retailers',     N'David Ross',    N'proposal',      N'medium',  55000.00,  60,  33000.00, CAST('2026-11-28' AS date), CAST(0 AS bit), CAST('2026-08-22 15:00:00' AS datetime2(3)))
        ) AS d(deal_name, account_name, owner_name, stage, priority, amount, probability_pct,
               expected_revenue, expected_close_date, is_won, created_at)
    )
    SELECT TOP (@MaxRows + 1)
        d.deal_name,
        d.account_name,
        d.owner_name,
        d.stage,
        d.priority,
        d.amount,
        d.probability_pct,
        d.expected_revenue,
        d.expected_close_date,
        d.is_won,
        d.created_at
    FROM SampleDeals AS d
    WHERE (@Priority  IS NULL OR d.priority = @Priority)
      AND (@MinAmount IS NULL OR d.amount >= @MinAmount)
      AND (@CloseFrom IS NULL OR d.expected_close_date >= @CloseFrom)
      AND (@CloseTo   IS NULL OR d.expected_close_date <= @CloseTo)
      AND (@IsWonOnly IS NULL OR @IsWonOnly = 0 OR d.is_won = 1)
      AND (NOT EXISTS (SELECT 1 FROM @Stages) OR d.stage IN (SELECT stage FROM @Stages))
    ORDER BY d.amount DESC;
END
GO

-- 3. crm_lead_analysis (tenant-owned report)
-- {"status": "qualified", "source": ["website","referral"], "min_score": 70,
--  "lead_date": {"from": "2026-08-01", "to": "2026-09-30"}}
CREATE OR ALTER PROCEDURE rpt.usp_crm_lead_analysis
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

    DECLARE @Status   varchar(30) = JSON_VALUE(@CriteriaJson, '$.status');
    DECLARE @MinScore int         = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.min_score') AS int);
    DECLARE @LeadFrom date        = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.lead_date.from') AS date);
    DECLARE @LeadTo   date        = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.lead_date.to')   AS date);

    DECLARE @Sources TABLE (source nvarchar(50) PRIMARY KEY);
    INSERT INTO @Sources (source)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.source') AS j
    WHERE j.[value] IS NOT NULL;

    WITH SampleLeads AS (
        SELECT * FROM (VALUES
            (N'Alexander Wright', N'AeroTech Dynamics', N'website',       N'converted',   92, 120000.00, CAST(1 AS bit), CAST('2026-08-05 09:15:00' AS datetime2(3))),
            (N'Claire Bennett',   N'Summit Logistics',  N'referral',      N'qualified',   85,  75000.00, CAST(0 AS bit), CAST('2026-08-12 11:30:00' AS datetime2(3))),
            (N'Marcus Vance',     N'Beacon Healthcare', N'trade_show',    N'contacted',   68,  50000.00, CAST(0 AS bit), CAST('2026-08-20 14:00:00' AS datetime2(3))),
            (N'Sophia Chen',      N'Solaria Energy',    N'partner',       N'converted',   95, 210000.00, CAST(1 AS bit), CAST('2026-08-28 16:20:00' AS datetime2(3))),
            (N'Liam O''Connor',   N'Pinnacle Advisory', N'cold_outreach', N'new',         45,  30000.00, CAST(0 AS bit), CAST('2026-09-02 10:45:00' AS datetime2(3))),
            (N'Grace Taylor',     N'Hyperion Motors',   N'social_media',  N'unqualified', 20,      0.00, CAST(0 AS bit), CAST('2026-09-10 13:10:00' AS datetime2(3))),
            (N'Benjamin Hayes',   N'IronClad Security', N'website',       N'qualified',   78,  90000.00, CAST(0 AS bit), CAST('2026-09-18 15:50:00' AS datetime2(3))),
            (N'Rachel Morgan',    N'Kestrel Avionics',  N'referral',      N'converted',   88, 160000.00, CAST(1 AS bit), CAST('2026-09-26 08:30:00' AS datetime2(3)))
        ) AS l(lead_name, company_name, source, status, lead_score, estimated_value,
               is_converted, created_at)
    )
    SELECT TOP (@MaxRows + 1)
        l.lead_name,
        l.company_name,
        l.source,
        l.status,
        l.lead_score,
        l.estimated_value,
        l.is_converted,
        l.created_at
    FROM SampleLeads AS l
    WHERE (@Status   IS NULL OR l.status = @Status)
      AND (@MinScore IS NULL OR l.lead_score >= @MinScore)
      AND (@LeadFrom IS NULL OR l.created_at >= @LeadFrom)
      AND (@LeadTo   IS NULL OR l.created_at <  DATEADD(day, 1, @LeadTo))
      AND (NOT EXISTS (SELECT 1 FROM @Sources) OR l.source IN (SELECT source FROM @Sources))
    ORDER BY l.lead_score DESC;
END
GO

-- ----------------------------------------------------------------------------
-- 5. Report Procedure: rpt.usp_crm_lead_list
-- ----------------------------------------------------------------------------
-- Sample criteria JSON:
-- {
--   "search_text": "Acme",
--   "status": ["new", "contacted"],
--   "lead_source_id": ["01J..."],
--   "industry_id": "01J...",
--   "owner_id": "01J...",
--   "is_hot_only": true,
--   "is_converted": false,
--   "created_date": {"from": "2026-01-01", "to": "2026-12-31"}
-- }
-- ----------------------------------------------------------------------------
CREATE OR ALTER PROCEDURE rpt.usp_crm_lead_list
    @CriteriaJson nvarchar(max),
    @MaxRows      int
AS
BEGIN
    SET NOCOUNT ON;

    -- 1. Tenant session context validation
    DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    -- 2. Criteria extraction & normalization
    IF @CriteriaJson IS NULL OR ISJSON(@CriteriaJson) = 0
        SET @CriteriaJson = N'{}';

    DECLARE @SearchText   nvarchar(200) = NULLIF(LTRIM(RTRIM(JSON_VALUE(@CriteriaJson, '$.search_text'))), '');
    DECLARE @IndustryId   varchar(26)   = NULLIF(JSON_VALUE(@CriteriaJson, '$.industry_id'), '');
    DECLARE @OwnerId      varchar(26)   = NULLIF(JSON_VALUE(@CriteriaJson, '$.owner_id'), '');
    DECLARE @IsHotOnly    bit           = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.is_hot_only') AS bit);
    DECLARE @IsConverted  bit           = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.is_converted') AS bit);
    DECLARE @CreatedFrom  date          = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.created_date.from') AS date);
    DECLARE @CreatedTo    date          = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.created_date.to')   AS date);

    -- Multiselect: status
    DECLARE @Statuses TABLE (status varchar(20) PRIMARY KEY);
    INSERT INTO @Statuses (status)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.status') AS j
    WHERE j.[value] IS NOT NULL AND j.[value] <> '';

    -- Multiselect: lead_source_id
    DECLARE @LeadSources TABLE (lead_source_id varchar(26) PRIMARY KEY);
    INSERT INTO @LeadSources (lead_source_id)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.lead_source_id') AS j
    WHERE j.[value] IS NOT NULL AND j.[value] <> '';

    -- 3. Query execution (TOP @MaxRows + 1 for governor detection)
    SELECT TOP (@MaxRows + 1)
        l.id,
        l.first_name,
        l.last_name,
        LTRIM(RTRIM(CONCAT(l.first_name, ' ', l.last_name))) AS full_name,
        l.company,
        l.title,
        l.email,
        l.phone,
        l.mobile,
        l.city,
        l.state,
        l.country,
        l.status,
        src.label                                             AS lead_source,
        ind.label                                             AS industry,
        LTRIM(RTRIM(CONCAT(u.first_name, ' ', u.last_name))) AS owner_name,
        l.revenue,
        l.employees,
        CAST(l.confidence AS int)                             AS confidence,
        l.is_hot,
        l.email_opt_out,
        l.is_converted,
        l.converted_at,
        l.created_at
    FROM crm.lead AS l
    LEFT JOIN crm.lookup AS src ON src.id = l.lead_source_id AND src.is_deleted = 0
    LEFT JOIN crm.lookup AS ind ON ind.id = l.industry_id AND ind.is_deleted = 0
    LEFT JOIN auth.tenant_user AS tu ON tu.id = l.owner_id AND tu.is_deleted = 0
    LEFT JOIN auth.app_user AS u ON u.id = tu.user_id AND u.is_deleted = 0
    WHERE l.tenant_id = @TenantId
      AND l.is_deleted = 0
      -- Search text filter
      AND (@SearchText IS NULL OR (
          l.first_name LIKE N'%' + @SearchText + N'%'
          OR l.last_name LIKE N'%' + @SearchText + N'%'
          OR l.company LIKE N'%' + @SearchText + N'%'
          OR l.email LIKE N'%' + @SearchText + N'%'
          OR l.phone LIKE N'%' + @SearchText + N'%'
      ))
      -- Status multiselect filter
      AND (NOT EXISTS (SELECT 1 FROM @Statuses) OR l.status IN (SELECT status FROM @Statuses))
      -- Lead source multiselect filter
      AND (NOT EXISTS (SELECT 1 FROM @LeadSources) OR l.lead_source_id IN (SELECT lead_source_id FROM @LeadSources))
      -- Industry dropdown filter
      AND (@IndustryId IS NULL OR l.industry_id = @IndustryId)
      -- Owner dropdown filter
      AND (@OwnerId IS NULL OR l.owner_id = @OwnerId)
      -- Bool flags
      AND (ISNULL(@IsHotOnly, 0) = 0 OR l.is_hot = 1)
      AND (@IsConverted IS NULL OR l.is_converted = @IsConverted)
      -- Date range filter
      AND (@CreatedFrom IS NULL OR l.created_at >= @CreatedFrom)
      AND (@CreatedTo   IS NULL OR l.created_at <  DATEADD(day, 1, @CreatedTo))
    ORDER BY l.created_at DESC;
END
GO

-- ============================================================================
-- Stored Procedure for Report: crm_lead_summary (Lead Summary by Status)
-- Schema: rpt
-- Target Database: Deevo Framework / CRM
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Report Procedure: rpt.usp_crm_lead_summary
-- Contract:
--   * Parameters: @CriteriaJson nvarchar(max), @MaxRows int
--   * Tenant isolation: SESSION_CONTEXT(N'tenant_id')
--   * Output: status (varchar), count (int)
-- ----------------------------------------------------------------------------
CREATE OR ALTER PROCEDURE rpt.usp_crm_lead_summary
    @CriteriaJson nvarchar(max),
    @MaxRows      int
AS
BEGIN
    SET NOCOUNT ON;

    -- 1. Validate tenant session context
    DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    -- 2. Extract criteria (optional created_date filter)
    IF @CriteriaJson IS NULL OR ISJSON(@CriteriaJson) = 0
        SET @CriteriaJson = N'{}';

    DECLARE @CreatedFrom date = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.created_date.from') AS date);
    DECLARE @CreatedTo   date = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.created_date.to')   AS date);

    -- 3. Query execution (TOP @MaxRows + 1 for governor detection)
    SELECT TOP (@MaxRows + 1)
        l.status,
        COUNT(*) AS [count]
    FROM crm.lead AS l
    WHERE l.tenant_id = @TenantId
      AND l.is_deleted = 0
      AND (@CreatedFrom IS NULL OR l.created_at >= @CreatedFrom)
      AND (@CreatedTo   IS NULL OR l.created_at <  DATEADD(day, 1, @CreatedTo))
    GROUP BY l.status
    ORDER BY [count] DESC, l.status ASC;
END
GO

-- Sample criteria:
-- { "search_text": "follow", "entity_type": ["account","lead"] }
CREATE OR ALTER PROCEDURE rpt.usp_crm_note_list
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

    DECLARE @SearchText nvarchar(200) = NULLIF(LTRIM(RTRIM(JSON_VALUE(@CriteriaJson, '$.search_text'))), '');

    DECLARE @EntityTypes TABLE (entity_type varchar(30) PRIMARY KEY);
    INSERT INTO @EntityTypes (entity_type)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.entity_type') AS j
    WHERE j.[value] IS NOT NULL AND j.[value] <> '';

    SELECT TOP (@MaxRows + 1)
        n.id,
        CASE
            WHEN LEN(n.body) > 80 THEN LEFT(n.body, 77) + N'...'
            ELSE n.body
        END AS body_preview,
        n.body,
        n.entity_type,
        n.entity_id,
        COALESCE(
            a.name,
            LTRIM(RTRIM(CONCAT(c.first_name, ' ', c.last_name))),
            LTRIM(RTRIM(CONCAT(l.first_name, ' ', l.last_name))),
            o.name,
            t.name
        ) AS entity_name,
        LTRIM(RTRIM(CONCAT(u.first_name, ' ', u.last_name))) AS created_by_name,
        n.created_at
    FROM crm.note AS n
    LEFT JOIN crm.account AS a
        ON n.entity_type = 'account' AND a.id = n.entity_id AND a.is_deleted = 0
    LEFT JOIN crm.contact AS c
        ON n.entity_type = 'contact' AND c.id = n.entity_id AND c.is_deleted = 0
    LEFT JOIN crm.lead AS l
        ON n.entity_type = 'lead' AND l.id = n.entity_id AND l.is_deleted = 0
    LEFT JOIN crm.opportunity AS o
        ON n.entity_type = 'opportunity' AND o.id = n.entity_id AND o.is_deleted = 0
    LEFT JOIN crm.task AS t
        ON n.entity_type = 'task' AND t.id = n.entity_id AND t.is_deleted = 0
    LEFT JOIN auth.app_user AS u
        ON u.id = n.created_by AND u.is_deleted = 0
    WHERE n.tenant_id = @TenantId
      AND n.is_deleted = 0
      AND (@SearchText IS NULL OR (
          n.body LIKE N'%' + @SearchText + N'%'
          OR a.name LIKE N'%' + @SearchText + N'%'
          OR c.first_name LIKE N'%' + @SearchText + N'%'
          OR c.last_name LIKE N'%' + @SearchText + N'%'
          OR l.first_name LIKE N'%' + @SearchText + N'%'
          OR l.last_name LIKE N'%' + @SearchText + N'%'
          OR o.name LIKE N'%' + @SearchText + N'%'
          OR t.name LIKE N'%' + @SearchText + N'%'
      ))
      AND (
          NOT EXISTS (SELECT 1 FROM @EntityTypes)
          OR n.entity_type IN (SELECT entity_type FROM @EntityTypes)
      )
    ORDER BY n.created_at DESC;
END
GO

-- Sample criteria:
-- { "search_text": "HVAC", "status": ["propose","won"], "account_id": "01J...", "owner_id": "01J..." }
CREATE OR ALTER PROCEDURE rpt.usp_crm_opportunity_list
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

    DECLARE @SearchText nvarchar(200) = NULLIF(LTRIM(RTRIM(JSON_VALUE(@CriteriaJson, '$.search_text'))), '');
    DECLARE @AccountId  varchar(26)   = NULLIF(JSON_VALUE(@CriteriaJson, '$.account_id'), '');
    DECLARE @OwnerId    varchar(26)   = NULLIF(JSON_VALUE(@CriteriaJson, '$.owner_id'), '');

    DECLARE @Statuses TABLE (status varchar(20) PRIMARY KEY);
    INSERT INTO @Statuses (status)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.status') AS j
    WHERE j.[value] IS NOT NULL AND j.[value] <> '';

    SELECT TOP (@MaxRows + 1)
        o.id,
        o.name,
        o.status,
        o.amount,
        o.confidence,
        o.close_date,
        o.next_step,
        a.name AS account_name,
        o.account_id,
        LTRIM(RTRIM(CONCAT(u.first_name, ' ', u.last_name))) AS owner_name,
        grp.label AS group_label,
        o.created_at
    FROM crm.opportunity AS o
    INNER JOIN crm.account AS a
        ON a.id = o.account_id AND a.is_deleted = 0
    LEFT JOIN crm.lookup AS grp
        ON grp.id = o.group_id AND grp.is_deleted = 0
    LEFT JOIN auth.tenant_user AS tu
        ON tu.id = o.owner_id AND tu.is_deleted = 0
    LEFT JOIN auth.app_user AS u
        ON u.id = tu.user_id AND u.is_deleted = 0
    WHERE o.tenant_id = @TenantId
      AND o.is_deleted = 0
      AND (@SearchText IS NULL OR (
          o.name LIKE N'%' + @SearchText + N'%'
          OR o.next_step LIKE N'%' + @SearchText + N'%'
          OR a.name LIKE N'%' + @SearchText + N'%'
      ))
      AND (NOT EXISTS (SELECT 1 FROM @Statuses) OR o.status IN (SELECT status FROM @Statuses))
      AND (@AccountId IS NULL OR o.account_id = @AccountId)
      AND (@OwnerId IS NULL OR o.owner_id = @OwnerId)
    ORDER BY o.created_at DESC;
END
GO

-- Sample criteria:
-- { "search_text": "Call", "status": ["open","hold"], "priority": ["high"], "account_id": "01J...", "owner_id": "01J..." }
CREATE OR ALTER PROCEDURE rpt.usp_crm_task_list
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

    DECLARE @SearchText nvarchar(200) = NULLIF(LTRIM(RTRIM(JSON_VALUE(@CriteriaJson, '$.search_text'))), '');
    DECLARE @AccountId  varchar(26)   = NULLIF(JSON_VALUE(@CriteriaJson, '$.account_id'), '');
    DECLARE @OwnerId    varchar(26)   = NULLIF(JSON_VALUE(@CriteriaJson, '$.owner_id'), '');

    DECLARE @Statuses TABLE (status varchar(20) PRIMARY KEY);
    INSERT INTO @Statuses (status)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.status') AS j
    WHERE j.[value] IS NOT NULL AND j.[value] <> '';

    DECLARE @Priorities TABLE (priority varchar(20) PRIMARY KEY);
    INSERT INTO @Priorities (priority)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.priority') AS j
    WHERE j.[value] IS NOT NULL AND j.[value] <> '';

    SELECT TOP (@MaxRows + 1)
        t.id,
        t.name,
        t.status,
        t.priority,
        t.due_date,
        a.name AS account_name,
        t.account_id,
        o.name AS opportunity_name,
        t.opportunity_id,
        LTRIM(RTRIM(CONCAT(u.first_name, ' ', u.last_name))) AS owner_name,
        t.created_at
    FROM crm.task AS t
    INNER JOIN crm.account AS a
        ON a.id = t.account_id AND a.is_deleted = 0
    LEFT JOIN crm.opportunity AS o
        ON o.id = t.opportunity_id AND o.is_deleted = 0
    LEFT JOIN auth.tenant_user AS tu
        ON tu.id = t.owner_id AND tu.is_deleted = 0
    LEFT JOIN auth.app_user AS u
        ON u.id = tu.user_id AND u.is_deleted = 0
    WHERE t.tenant_id = @TenantId
      AND t.is_deleted = 0
      AND (@SearchText IS NULL OR (
          t.name LIKE N'%' + @SearchText + N'%'
          OR t.description LIKE N'%' + @SearchText + N'%'
          OR a.name LIKE N'%' + @SearchText + N'%'
          OR o.name LIKE N'%' + @SearchText + N'%'
      ))
      AND (NOT EXISTS (SELECT 1 FROM @Statuses) OR t.status IN (SELECT status FROM @Statuses))
      AND (NOT EXISTS (SELECT 1 FROM @Priorities) OR t.priority IN (SELECT priority FROM @Priorities))
      AND (@AccountId IS NULL OR t.account_id = @AccountId)
      AND (@OwnerId IS NULL OR t.owner_id = @OwnerId)
    ORDER BY t.created_at DESC;
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

-- ----------------------------------------------------------------------------
-- 3. Lookup: Account Owner (Tenant Staff Users) — same shape as lead owner
-- ----------------------------------------------------------------------------
CREATE OR ALTER PROCEDURE rpt.usp_lookup_account_owner
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
        tu.id AS value,
        LTRIM(RTRIM(CONCAT(u.first_name, ' ', u.last_name))) AS label
    FROM auth.tenant_user AS tu
    INNER JOIN auth.app_user AS u ON u.id = tu.user_id AND u.is_deleted = 0
    WHERE tu.tenant_id = @TenantId
      AND tu.is_deleted = 0
      AND tu.is_active = 1
      AND (@SearchText IS NULL OR LTRIM(RTRIM(CONCAT(u.first_name, ' ', u.last_name))) LIKE N'%' + @SearchText + N'%' OR u.email LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR tu.id IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY label;
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

-- ============================================================================
-- Stored Procedures for Report: crm_account_list (CRM Accounts List)
-- Schema: rpt
-- Target Database: deevo_app_dev2
-- Run as deevo_ddl. Safe to re-run (CREATE OR ALTER).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Lookup: Account Type (fixed enum matching app AccountType)
-- ----------------------------------------------------------------------------
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
        (N'press',    N'Press',    2),
        (N'charity',  N'Charity',  3),
        (N'partner',  N'Partner',  4),
        (N'prospect', N'Prospect', 5),
        (N'reseller', N'Reseller', 6),
        (N'other',    N'Other',    7)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
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

-- ============================================================================
-- Stored Procedures for Report: crm_contact_list (CRM - Contacts)
-- Schema: rpt
-- Target Database: deevo_app_dev2
-- Run as deevo_ddl. Safe to re-run (CREATE OR ALTER).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Lookup: CRM Account (for report criteria)
-- ----------------------------------------------------------------------------
CREATE OR ALTER PROCEDURE rpt.usp_lookup_crm_account
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
        a.id AS value,
        a.name AS label
    FROM crm.account AS a
    WHERE a.tenant_id = @TenantId
      AND a.is_deleted = 0
      AND (@SearchText IS NULL OR a.name LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR a.id IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY a.name;
END
GO

-- ----------------------------------------------------------------------------
-- 2. Lookup: Account Group (Tenant Custom / crm.lookup)
-- ----------------------------------------------------------------------------
CREATE OR ALTER PROCEDURE rpt.usp_lookup_crm_account_group
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
        l.id AS value,
        l.label AS label
    FROM crm.lookup AS l
    WHERE l.tenant_id = @TenantId
      AND l.category = 'account_group'
      AND l.is_deleted = 0
      AND l.is_active = 1
      AND (@SearchText IS NULL OR l.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR l.id IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY l.display_order, l.label;
END
GO

-- ----------------------------------------------------------------------------
-- 3. Lookup: Industry (Tenant Custom / crm.lookup)
-- ----------------------------------------------------------------------------
CREATE OR ALTER PROCEDURE rpt.usp_lookup_crm_industry
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
        l.id AS value,
        l.label AS label
    FROM crm.lookup AS l
    WHERE l.tenant_id = @TenantId
      AND l.category = 'industry'
      AND l.is_deleted = 0
      AND l.is_active = 1
      AND (@SearchText IS NULL OR l.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR l.id IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY l.display_order, l.label;
END
GO

-- ----------------------------------------------------------------------------
-- 2. Lookup: Lead Source (Tenant Custom / crm.lookup)
-- ----------------------------------------------------------------------------
CREATE OR ALTER PROCEDURE rpt.usp_lookup_crm_lead_source
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
        l.id AS value,
        l.label AS label
    FROM crm.lookup AS l
    WHERE l.tenant_id = @TenantId
      AND l.category = 'lead_source'
      AND l.is_deleted = 0
      AND l.is_active = 1
      AND (@SearchText IS NULL OR l.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR l.id IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY l.display_order, l.label;
END
GO

CREATE OR ALTER PROCEDURE rpt.usp_lookup_crm_opportunity_group
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
        l.id AS value,
        l.label AS label
    FROM crm.lookup AS l
    WHERE l.tenant_id = @TenantId
      AND l.category = 'opportunity_group'
      AND l.is_deleted = 0
      AND l.is_active = 1
      AND (@SearchText IS NULL OR l.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR l.id IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY l.display_order, l.label;
END
GO

CREATE OR ALTER PROCEDURE rpt.usp_lookup_deal_priority
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'low',    N'Low',    1),
        (N'medium', N'Medium', 2),
        (N'high',   N'High',   3),
        (N'urgent', N'Urgent', 4)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
END
GO

-- ============================================================================
-- DeevoFlow development reports for the mtf generic report writer (rpt schema)
-- ============================================================================
-- Run in SSMS as deevo_ddl AFTER the framework scripts in deevo_mt_framework_backend:
--   docs/rpt_schema_v5.sql           (tables)
--   docs/rpt_seed_sample_report.sql  (grants for deevo_app, framework sample reports)
--
-- Development data only: the report procs return a fixed sample data set (no product
-- tables), keyed to whichever tenant is in SESSION_CONTEXT, so every tenant sees rows.
-- Safe to re-run:
--   * procs use CREATE OR ALTER
--   * catalog metadata for the report keys below (and the older 01JRPT0DF ids) is DELETED
--     and re-inserted in one transaction, including any saved views on those reports.
--
--   report_key              scope    proc                            lookups
--   ----------------------  -------  ------------------------------  -----------------------------
--   crm_deal_pipeline       system   rpt.usp_crm_deal_pipeline       deal_stage, deal_priority
--   sales_invoice_summary   system   rpt.usp_sales_invoice_summary   invoice_status, payment_terms
--   crm_lead_analysis       tenant   rpt.usp_crm_lead_analysis       lead_status, lead_source
--
-- crm_lead_analysis is a tenant-owned report (only @DevTenantId sees it) so the tenant
-- report path has something to exercise. Change @DevTenantId below for another dev tenant;
-- the report is skipped if that tenant doesn't exist.
--
-- IDs use the 01JRPTDVF prefix (framework samples use 01JRPTMTF).
--
-- Proc contracts (full spec: deevo_mt_framework_backend/prompts/REPORT_API_PROMPT.md):
--   Report proc: (@CriteriaJson nvarchar(max), @MaxRows int)
--     * criteria absent from @CriteriaJson mean "no filter"
--     * final SELECT uses TOP (@MaxRows + 1) so the API can detect truncation
--     * result-set column names exactly match the report's active report_column rows
--   Lookup proc: (@SearchText nvarchar(200) = NULL, @Values nvarchar(max) = NULL,
--                 @MaxRows int = 50)
--     * @Values is a JSON array of value strings; TOP (@MaxRows + 1)
--     * returns exactly two columns: [value] (always a string) and [label]
--   Report procs read the tenant from SESSION_CONTEXT(N'tenant_id') and THROW if unset.
-- ============================================================================

-- ============================================================================
-- Lookup procs (static value lists)
-- ============================================================================
CREATE OR ALTER PROCEDURE rpt.usp_lookup_deal_stage
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'prospecting',   N'Prospecting',   1),
        (N'qualification', N'Qualification', 2),
        (N'proposal',      N'Proposal',      3),
        (N'negotiation',   N'Negotiation',   4),
        (N'closed_won',    N'Closed Won',    5),
        (N'closed_lost',   N'Closed Lost',   6)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
END
GO

CREATE OR ALTER PROCEDURE rpt.usp_lookup_invoice_status
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'draft',     N'Draft',     1),
        (N'sent',      N'Sent',      2),
        (N'paid',      N'Paid',      3),
        (N'partial',   N'Partial',   4),
        (N'overdue',   N'Overdue',   5),
        (N'cancelled', N'Cancelled', 6)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
END
GO

-- ----------------------------------------------------------------------------
-- 4. Lookup: Lead Owner (Tenant Staff Users)
-- ----------------------------------------------------------------------------
CREATE OR ALTER PROCEDURE rpt.usp_lookup_lead_owner
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
        tu.id AS value,
        LTRIM(RTRIM(CONCAT(u.first_name, ' ', u.last_name))) AS label
    FROM auth.tenant_user AS tu
    INNER JOIN auth.app_user AS u ON u.id = tu.user_id AND u.is_deleted = 0
    WHERE tu.tenant_id = @TenantId
      AND tu.is_deleted = 0
      AND tu.is_active = 1
      AND (@SearchText IS NULL OR LTRIM(RTRIM(CONCAT(u.first_name, ' ', u.last_name))) LIKE N'%' + @SearchText + N'%' OR u.email LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR tu.id IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY label;
END
GO

CREATE OR ALTER PROCEDURE rpt.usp_lookup_lead_source
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'website',       N'Website Organic', 1),
        (N'referral',      N'Referral',        2),
        (N'cold_outreach', N'Cold Outreach',   3),
        (N'trade_show',    N'Trade Show',      4),
        (N'partner',       N'Partner Channel', 5),
        (N'social_media',  N'Social Media',    6)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
END
GO

-- ============================================================================
-- Stored Procedures for Report: crm_lead_list (Leads List)
-- Schema: rpt
-- Target Database: Deevo Framework / CRM
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Lookup: Lead Status
-- ----------------------------------------------------------------------------
CREATE OR ALTER PROCEDURE rpt.usp_lookup_lead_status
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'new',         N'New / Uncontacted', 1),
        (N'contacted',   N'Contacted',         2),
        (N'in_progress', N'In Progress',       3),
        (N'qualified',   N'Qualified',         4),
        (N'unqualified', N'Unqualified',       5),
        (N'lost',        N'Lost',              6)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
END
GO

-- ============================================================================
-- Stored Procedures for Report: crm_note_list (CRM - Notes)
-- Schema: rpt — Target: deevo_app_dev2 — Safe to re-run (CREATE OR ALTER).
-- ============================================================================

CREATE OR ALTER PROCEDURE rpt.usp_lookup_note_entity_type
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'account',     N'Account',     1),
        (N'contact',     N'Contact',     2),
        (N'lead',        N'Lead',        3),
        (N'opportunity', N'Opportunity', 4),
        (N'task',        N'Task',        5)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
END
GO

-- ============================================================================
-- Stored Procedures for Report: crm_opportunity_list (CRM - Opportunity)
-- Schema: rpt — Target: deevo_app_dev2 — Safe to re-run (CREATE OR ALTER).
-- ============================================================================

CREATE OR ALTER PROCEDURE rpt.usp_lookup_opportunity_status
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'none',    N'None',    1),
        (N'qualify', N'Qualify', 2),
        (N'meet',    N'Meet',    3),
        (N'propose', N'Propose', 4),
        (N'won',     N'Won',     5),
        (N'lost',    N'Lost',    6)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
END
GO

CREATE OR ALTER PROCEDURE rpt.usp_lookup_payment_terms
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'due_on_receipt', N'Due on Receipt', 1),
        (N'net_15',         N'Net 15 Days',    2),
        (N'net_30',         N'Net 30 Days',    3),
        (N'net_60',         N'Net 60 Days',    4)
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

CREATE OR ALTER PROCEDURE rpt.usp_lookup_task_priority
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'low',    N'Low',    1),
        (N'medium', N'Medium', 2),
        (N'high',   N'High',   3)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
END
GO

-- ============================================================================
-- Stored Procedures for Report: crm_task_list (CRM - Tasks)
-- Schema: rpt — Target: deevo_app_dev2 — Safe to re-run (CREATE OR ALTER).
-- ============================================================================

CREATE OR ALTER PROCEDURE rpt.usp_lookup_task_status
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'open',   N'Open',   1),
        (N'hold',   N'Hold',   2),
        (N'closed', N'Closed', 3)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
END
GO

CREATE OR ALTER PROCEDURE rpt.usp_lookup_tenant_user_role
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    SELECT TOP (@MaxRows + 1) v.value, v.label
    FROM (VALUES
        (N'admin',  N'Admin',  1),
        (N'member', N'Member', 2)
    ) AS v(value, label, sort_order)
    WHERE (@SearchText IS NULL OR v.label LIKE N'%' + @SearchText + N'%')
      AND (@Values IS NULL OR v.value IN (SELECT j.[value] FROM OPENJSON(@Values) AS j))
    ORDER BY v.sort_order;
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

-- 2. sales_invoice_summary
-- {"status": ["sent","overdue"], "payment_terms": ["net_30"],
--  "invoice_date": {"from": "2026-08-01"}, "overdue_only": true, "min_balance": 1000}
CREATE OR ALTER PROCEDURE rpt.usp_sales_invoice_summary
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

    DECLARE @InvoiceFrom date          = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.invoice_date.from') AS date);
    DECLARE @InvoiceTo   date          = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.invoice_date.to')   AS date);
    DECLARE @OverdueOnly bit           = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.overdue_only') AS bit);
    DECLARE @MinBalance  decimal(18,2) = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.min_balance') AS decimal(18,2));

    DECLARE @Statuses TABLE (status nvarchar(30) PRIMARY KEY);
    INSERT INTO @Statuses (status)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.status') AS j
    WHERE j.[value] IS NOT NULL;

    DECLARE @Terms TABLE (payment_terms nvarchar(30) PRIMARY KEY);
    INSERT INTO @Terms (payment_terms)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.payment_terms') AS j
    WHERE j.[value] IS NOT NULL;

    WITH SampleInvoices AS (
        SELECT * FROM (VALUES
            (N'INV-2026-001', N'Acme Global Corp',     CAST('2026-08-01' AS date), CAST('2026-08-31' AS date), N'paid',    N'net_30',         45000.00, 3600.00,  48600.00,     0.00, CAST(0 AS bit)),
            (N'INV-2026-002', N'Vertex Logistics',     CAST('2026-08-15' AS date), CAST('2026-09-14' AS date), N'overdue', N'net_30',         82000.00, 6560.00,  88560.00, 88560.00, CAST(1 AS bit)),
            (N'INV-2026-003', N'Nexus Media Group',    CAST('2026-09-01' AS date), CAST('2026-09-16' AS date), N'overdue', N'net_15',         18500.00, 1480.00,  19980.00, 19980.00, CAST(1 AS bit)),
            (N'INV-2026-004', N'Quantix Capital',      CAST('2026-09-10' AS date), CAST('2026-10-10' AS date), N'partial', N'net_30',         95000.00, 7600.00, 102600.00, 50000.00, CAST(0 AS bit)),
            (N'INV-2026-005', N'BluePeak Financial',   CAST('2026-09-20' AS date), CAST('2026-10-20' AS date), N'sent',    N'net_30',         32000.00, 2560.00,  34560.00, 34560.00, CAST(0 AS bit)),
            (N'INV-2026-006', N'Omega Health Systems', CAST('2026-09-25' AS date), CAST('2026-09-25' AS date), N'paid',    N'due_on_receipt', 12000.00,  960.00,  12960.00,     0.00, CAST(0 AS bit)),
            (N'INV-2026-007', N'Zenith Retailers',     CAST('2026-09-28' AS date), CAST('2026-11-27' AS date), N'draft',   N'net_60',         64000.00, 5120.00,  69120.00, 69120.00, CAST(0 AS bit))
        ) AS i(invoice_number, customer_name, invoice_date, due_date, status, payment_terms,
               subtotal, tax_amount, total_amount, balance_due, is_overdue)
    )
    SELECT TOP (@MaxRows + 1)
        i.invoice_number,
        i.customer_name,
        i.invoice_date,
        i.due_date,
        i.status,
        i.payment_terms,
        i.subtotal,
        i.tax_amount,
        i.total_amount,
        i.balance_due,
        i.is_overdue
    FROM SampleInvoices AS i
    WHERE (@InvoiceFrom IS NULL OR i.invoice_date >= @InvoiceFrom)
      AND (@InvoiceTo   IS NULL OR i.invoice_date <= @InvoiceTo)
      AND (@OverdueOnly IS NULL OR @OverdueOnly = 0 OR i.is_overdue = 1)
      AND (@MinBalance  IS NULL OR i.balance_due >= @MinBalance)
      AND (NOT EXISTS (SELECT 1 FROM @Statuses) OR i.status IN (SELECT status FROM @Statuses))
      AND (NOT EXISTS (SELECT 1 FROM @Terms)
           OR i.payment_terms IN (SELECT payment_terms FROM @Terms))
    ORDER BY i.invoice_date DESC;
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
