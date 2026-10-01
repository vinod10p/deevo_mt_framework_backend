-- ============================================================================
-- rpt schema — Generic Reporting Framework
-- Updated to conform to: Database Schema Standards v1.0 (deevo_app_dev2, June 2026)
-- ============================================================================
-- Conventions applied throughout:
--   * snake_case table/column names, singular table nouns
--   * id varchar(26) ULID (app-generated) as clustered PK on every table
--   * tenant_id as the 2nd column on every table, EXCEPT report_column and report_criteria —
--     child metadata tables whose tenant is fully derived via report_id -> report_definition,
--     never owned independently (see comment above each table for why storing it there was
--     both redundant and, under a composite FK, silently unenforced for system-wide reports)
--   * On the three tables that DO carry a nullable tenant_id (report_definition and the two
--     saved-view tables), nullability is paired with an explicit scope_type
--     ('system'/'tenant'[/'user']) enum + CHECK constraint, so the meaning is self-documenting
--     rather than inferred from NULL alone — mirrors the auth.app_user exception pattern in
--     the standard for system-level rows
--   * Standard audit column block: is_active, is_deleted, row_version,
--     created_at, updated_at, created_by, updated_by, deleted_by
--   * No hard deletes / no ON DELETE CASCADE — soft delete only (is_deleted)
--   * Enum-like varchar columns use lowercase string values + named CK_ constraint
--   * JSON columns use nvarchar(max) + ISJSON() CK_ constraint
--   * All constraints/indexes named per PK_/UQ_/FK_/CK_/DF_/IX_ conventions
-- ============================================================================

create schema rpt
go 
-- ============================================================================
-- 1. rpt.report_definition — the report registry
-- ============================================================================
CREATE TABLE [rpt].[report_definition] (
    [id]                varchar(26)     NOT NULL,
    [tenant_id]         varchar(26)     NULL,        -- NULL only when scope_type = 'system' — see CK_report_definition_scope

    [scope_type]        varchar(10)     NOT NULL,    -- 'system' = platform-wide, 'tenant' = tenant-custom
    [report_key]        varchar(100)    NOT NULL,    -- stable public identifier, e.g. 'SalesByRegion'
    [display_name]      nvarchar(200)   NOT NULL,
    [proc_name]         varchar(256)    NOT NULL,    -- e.g. 'rpt.usp_sales_by_region'
    [description]       nvarchar(500)   NULL,
    [default_max_rows]  int             NOT NULL,    -- passed to the proc as @MaxRows

    [is_active]         bit             NOT NULL,
    [is_deleted]        bit             NOT NULL,
    [row_version]       timestamp       NOT NULL,
    [created_at]        datetime2(3)    NOT NULL,
    [updated_at]        datetime2(3)    NOT NULL,
    [created_by]        varchar(26)     NULL,
    [updated_by]        varchar(26)     NULL,
    [deleted_by]        varchar(26)     NULL,

    CONSTRAINT [PK_report_definition] PRIMARY KEY CLUSTERED ([id] ASC)
);

ALTER TABLE [rpt].[report_definition] ADD
    CONSTRAINT [DF_report_definition_scope_type]       DEFAULT ('tenant')         FOR [scope_type],
    CONSTRAINT [DF_report_definition_default_max_rows] DEFAULT ((20000))          FOR [default_max_rows],
    CONSTRAINT [DF_report_definition_is_active]        DEFAULT ((1))              FOR [is_active],
    CONSTRAINT [DF_report_definition_is_deleted]       DEFAULT ((0))              FOR [is_deleted],
    CONSTRAINT [DF_report_definition_created_at]       DEFAULT (sysutcdatetime()) FOR [created_at],
    CONSTRAINT [DF_report_definition_updated_at]       DEFAULT (sysutcdatetime()) FOR [updated_at];

ALTER TABLE [rpt].[report_definition] WITH CHECK ADD
    CONSTRAINT [FK_report_definition_tenant_id]  FOREIGN KEY ([tenant_id])  REFERENCES [tenant].[tenant] ([id]),
    CONSTRAINT [FK_report_definition_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_definition_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_definition_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user] ([id]);

ALTER TABLE [rpt].[report_definition] WITH CHECK ADD
    CONSTRAINT [CK_report_definition_scope_type] CHECK ([scope_type] IN ('system','tenant')),
    -- explicit, self-documenting pairing — mirrors the scope pattern on report_saved_criteria/report_saved_layout
    CONSTRAINT [CK_report_definition_scope] CHECK (
        ([scope_type] = 'system' AND [tenant_id] IS NULL) OR
        ([scope_type] = 'tenant' AND [tenant_id] IS NOT NULL)
    );

-- report_key unique per tenant, and unique among system-wide (scope_type = 'system') reports.
-- Scoped to is_deleted = 0 so a soft-deleted report's key can be reused.
CREATE UNIQUE INDEX [UQ_report_definition_system] ON [rpt].[report_definition] ([report_key])
    WHERE [scope_type] = 'system' AND [is_deleted] = 0;
CREATE UNIQUE INDEX [UQ_report_definition_tenant] ON [rpt].[report_definition] ([tenant_id], [report_key])
    WHERE [scope_type] = 'tenant' AND [is_deleted] = 0;

CREATE NONCLUSTERED INDEX [IX_report_definition_tenant_id]
    ON [rpt].[report_definition] ([tenant_id], [is_deleted]);


-- ============================================================================
-- 2. rpt.report_column — column metadata per report
-- ============================================================================
-- No tenant_id here by design: it's fully derived via report_id -> report_definition.tenant_id.
-- (A composite FK (report_id, tenant_id) was tried in an earlier version, but SQL Server only
-- supports MATCH SIMPLE for multi-column FKs — if any one column is NULL, the WHOLE constraint
-- is skipped for that row. Every column belonging to a system-wide report has tenant_id = NULL,
-- so that composite FK silently stopped validating report_id existed at all for those rows.
-- Storing it here was also pure redundancy: a column has no tenant identity independent of
-- its parent report.)
CREATE TABLE [rpt].[report_column] (
    [id]                varchar(26)     NOT NULL,

    [report_id]         varchar(26)     NOT NULL,
    [column_name]       varchar(128)    NOT NULL,    -- must match the proc's output column
    [display_name]      nvarchar(200)   NOT NULL,
    [data_type]         varchar(30)     NOT NULL,
    [display_order]     int             NOT NULL,
    [is_displayable]    bit             NOT NULL,    -- can this column ever appear as a grid column
    [is_default_visible] bit            NOT NULL,    -- only meaningful when is_displayable = 1
    [is_sortable]       bit             NOT NULL,    -- only meaningful when is_displayable = 1
    [is_groupable]      bit             NOT NULL,    -- only meaningful when is_displayable = 1
    [is_filterable]     bit             NOT NULL,    -- shows up in the filter picker, regardless of is_displayable
    [is_aggregatable]   bit             NOT NULL,    -- can this column be summarized in a group footer/total row
    [default_aggregate_type] varchar(10) NULL,       -- initial pick (sum/avg/count/min/max); user can change it in-grid
    [display_format]    varchar(50)     NULL,        -- e.g. 'currency', 'percent', 'MM/dd/yyyy' — named formats preferred over raw format strings
    [default_width]     int             NULL,        -- initial grid column width in px; a saved layout can override it

    [is_active]         bit             NOT NULL,
    [is_deleted]        bit             NOT NULL,
    [row_version]       timestamp       NOT NULL,
    [created_at]        datetime2(3)    NOT NULL,
    [updated_at]        datetime2(3)    NOT NULL,
    [created_by]        varchar(26)     NULL,
    [updated_by]        varchar(26)     NULL,
    [deleted_by]        varchar(26)     NULL,

    CONSTRAINT [PK_report_column] PRIMARY KEY CLUSTERED ([id] ASC)
);

ALTER TABLE [rpt].[report_column] ADD
    CONSTRAINT [DF_report_column_is_displayable]     DEFAULT ((1))              FOR [is_displayable],
    CONSTRAINT [DF_report_column_is_default_visible] DEFAULT ((1))              FOR [is_default_visible],
    CONSTRAINT [DF_report_column_is_sortable]     DEFAULT ((1))              FOR [is_sortable],
    CONSTRAINT [DF_report_column_is_groupable]    DEFAULT ((0))              FOR [is_groupable],
    CONSTRAINT [DF_report_column_is_filterable]   DEFAULT ((1))              FOR [is_filterable],
    CONSTRAINT [DF_report_column_is_aggregatable] DEFAULT ((0))              FOR [is_aggregatable],
    CONSTRAINT [DF_report_column_is_active]       DEFAULT ((1))              FOR [is_active],
    CONSTRAINT [DF_report_column_is_deleted]      DEFAULT ((0))              FOR [is_deleted],
    CONSTRAINT [DF_report_column_created_at]      DEFAULT (sysutcdatetime()) FOR [created_at],
    CONSTRAINT [DF_report_column_updated_at]      DEFAULT (sysutcdatetime()) FOR [updated_at];

ALTER TABLE [rpt].[report_column] WITH CHECK ADD
    CONSTRAINT [FK_report_column_report_id] FOREIGN KEY ([report_id]) REFERENCES [rpt].[report_definition] ([id]),
    CONSTRAINT [FK_report_column_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_column_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_column_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user] ([id]);

ALTER TABLE [rpt].[report_column] WITH CHECK ADD
    CONSTRAINT [CK_report_column_data_type]      CHECK ([data_type] IN ('string','int','decimal','date','datetime','bool')),
    CONSTRAINT [CK_report_column_default_aggregate_type] CHECK ([default_aggregate_type] IS NULL OR [default_aggregate_type] IN ('sum','avg','count','min','max')),
    -- a column that can never be displayed can't be "shown by default", sortable, or groupable
    CONSTRAINT [CK_report_column_display] CHECK (
        [is_displayable] = 1 OR ([is_default_visible] = 0 AND [is_sortable] = 0 AND [is_groupable] = 0)
    ),
    -- a non-aggregatable column can't carry a default aggregate function
    CONSTRAINT [CK_report_column_aggregatable] CHECK (
        [is_aggregatable] = 1 OR [default_aggregate_type] IS NULL
    );

CREATE UNIQUE INDEX [UQ_report_column] ON [rpt].[report_column] ([report_id], [column_name])
    WHERE [is_deleted] = 0;

CREATE NONCLUSTERED INDEX [IX_report_column_report_id] ON [rpt].[report_column] ([report_id]);


-- ============================================================================
-- 3. rpt.report_criteria — pre-run filter/criteria panel metadata per report
-- ============================================================================
-- No tenant_id here by design — same rationale as report_column: fully derived via
-- report_id -> report_definition.tenant_id, and never independently owned by a tenant.
CREATE TABLE [rpt].[report_criteria] (
    [id]                varchar(26)     NOT NULL,

    [report_id]         varchar(26)     NOT NULL,
    -- one row = one rendered filter-panel field. The JSON value shape under criteria_key,
    -- once submitted, depends on control_type: scalar for text/number/date/dropdown/bool,
    -- array for multiselect, {"from":..., "to":...} object for daterange — e.g.
    -- {"invoice_date": {"from": "2026-01-01", "to": "2026-01-31"}}. OPENJSON's WITH clause
    -- reads nested paths natively ('$.invoice_date.from'), so this needs no schema change.
    [criteria_key]      varchar(100)    NOT NULL,    -- matches the JSON key the proc expects
    [display_name]      nvarchar(200)   NOT NULL,
    [data_type]         varchar(30)     NOT NULL,    -- type of the value once collected — drives JSON encoding
    [control_type]      varchar(30)     NOT NULL,    -- which input widget to render
    -- every lookup_proc must return exactly two columns named `value` and `label` —
    -- a fixed contract, not per-proc naming, so the front-end dropdown component stays generic
    [lookup_proc]       varchar(256)    NULL,        -- populates dropdown/multiselect options
    -- literal values ('Open', 'US') store as-is. Reserve a convention for dynamic values —
    -- @today, @month_start, @year_start, @current_user, @current_tenant — resolved by the
    -- app layer at render time. No schema change needed to add this later.
    [default_value]     nvarchar(500)   NULL,
    [is_required]       bit             NOT NULL,
    [display_order]     int             NOT NULL,

    [is_active]         bit             NOT NULL,
    [is_deleted]        bit             NOT NULL,
    [row_version]       timestamp       NOT NULL,
    [created_at]        datetime2(3)    NOT NULL,
    [updated_at]        datetime2(3)    NOT NULL,
    [created_by]        varchar(26)     NULL,
    [updated_by]        varchar(26)     NULL,
    [deleted_by]        varchar(26)     NULL,

    CONSTRAINT [PK_report_criteria] PRIMARY KEY CLUSTERED ([id] ASC)
);

ALTER TABLE [rpt].[report_criteria] ADD
    CONSTRAINT [DF_report_criteria_is_required] DEFAULT ((0))              FOR [is_required],
    CONSTRAINT [DF_report_criteria_is_active]   DEFAULT ((1))              FOR [is_active],
    CONSTRAINT [DF_report_criteria_is_deleted]  DEFAULT ((0))              FOR [is_deleted],
    CONSTRAINT [DF_report_criteria_created_at]  DEFAULT (sysutcdatetime()) FOR [created_at],
    CONSTRAINT [DF_report_criteria_updated_at]  DEFAULT (sysutcdatetime()) FOR [updated_at];

ALTER TABLE [rpt].[report_criteria] WITH CHECK ADD
    CONSTRAINT [FK_report_criteria_report_id] FOREIGN KEY ([report_id]) REFERENCES [rpt].[report_definition] ([id]),
    CONSTRAINT [FK_report_criteria_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_criteria_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_criteria_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user] ([id]);

ALTER TABLE [rpt].[report_criteria] WITH CHECK ADD
    CONSTRAINT [CK_report_criteria_control_type] CHECK ([control_type] IN ('text','number','date','daterange','dropdown','multiselect','bool')),
    CONSTRAINT [CK_report_criteria_data_type]    CHECK ([data_type] IN ('string','int','decimal','date','datetime','bool')),
    -- keeps obviously-wrong pairings out: a bool control must carry bool data, a date/daterange
    -- control must carry a date-ish data type, a number control must carry int or decimal
    CONSTRAINT [CK_report_criteria_control_data] CHECK (
        ([control_type] = 'bool'                      AND [data_type] = 'bool') OR
        ([control_type] IN ('date','daterange')       AND [data_type] IN ('date','datetime')) OR
        ([control_type] = 'number'                    AND [data_type] IN ('int','decimal')) OR
        ([control_type] IN ('text','dropdown','multiselect'))
    );

CREATE UNIQUE INDEX [UQ_report_criteria] ON [rpt].[report_criteria] ([report_id], [criteria_key])
    WHERE [is_deleted] = 0;

CREATE NONCLUSTERED INDEX [IX_report_criteria_report_id] ON [rpt].[report_criteria] ([report_id]);


-- ============================================================================
-- 4. rpt.report_saved_criteria — System / Tenant / User scoped saved criteria presets
-- ============================================================================
-- App-layer rule (not DB-enforced — a cross-table CHECK needs a UDF, avoided for write
-- perf): IF report_definition.scope_type = 'tenant' THEN this row's tenant_id MUST equal
-- report_definition.tenant_id. For a 'system' report, any tenant/user override is allowed.
-- This must land in the service layer with a test before saved criteria can be written.
CREATE TABLE [rpt].[report_saved_criteria] (
    [id]                varchar(26)     NOT NULL,
    [tenant_id]         varchar(26)     NULL,        -- NULL only when scope_type = 'system'

    [report_id]         varchar(26)     NOT NULL,
    [scope_type]        varchar(10)     NOT NULL,    -- system / tenant / user
    [user_id]           varchar(26)     NULL,        -- required only when scope_type = 'user'
    [criteria_name]     nvarchar(200)   NOT NULL,
    -- key-value pairs keyed by report_criteria.criteria_key for this report. Always include
    -- a top-level "version" int so the app can migrate older saved rows if the shape changes,
    -- e.g. {"version": 1, "invoice_date": {"from": "...", "to": "..."}, "status": "Open"}
    [criteria_json]     nvarchar(max)   NOT NULL,
    [is_default]        bit             NOT NULL,

    [is_active]         bit             NOT NULL,
    [is_deleted]        bit             NOT NULL,
    [row_version]       timestamp       NOT NULL,
    [created_at]        datetime2(3)    NOT NULL,
    [updated_at]        datetime2(3)    NOT NULL,
    [created_by]        varchar(26)     NULL,
    [updated_by]        varchar(26)     NULL,
    [deleted_by]        varchar(26)     NULL,

    CONSTRAINT [PK_report_saved_criteria] PRIMARY KEY CLUSTERED ([id] ASC)
);

ALTER TABLE [rpt].[report_saved_criteria] ADD
    CONSTRAINT [DF_report_saved_criteria_is_default] DEFAULT ((0))              FOR [is_default],
    CONSTRAINT [DF_report_saved_criteria_is_active]  DEFAULT ((1))              FOR [is_active],
    CONSTRAINT [DF_report_saved_criteria_is_deleted] DEFAULT ((0))              FOR [is_deleted],
    CONSTRAINT [DF_report_saved_criteria_created_at] DEFAULT (sysutcdatetime()) FOR [created_at],
    CONSTRAINT [DF_report_saved_criteria_updated_at] DEFAULT (sysutcdatetime()) FOR [updated_at];

ALTER TABLE [rpt].[report_saved_criteria] WITH CHECK ADD
    CONSTRAINT [FK_report_saved_criteria_report_id]  FOREIGN KEY ([report_id])  REFERENCES [rpt].[report_definition] ([id]),
    CONSTRAINT [FK_report_saved_criteria_tenant_id]  FOREIGN KEY ([tenant_id])  REFERENCES [tenant].[tenant] ([id]),
    CONSTRAINT [FK_report_saved_criteria_user_id]    FOREIGN KEY ([user_id])    REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_saved_criteria_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_saved_criteria_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_saved_criteria_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user] ([id]);

ALTER TABLE [rpt].[report_saved_criteria] WITH CHECK ADD
    CONSTRAINT [CK_report_saved_criteria_scope] CHECK (
        ([scope_type] = 'system' AND [tenant_id] IS NULL     AND [user_id] IS NULL) OR
        ([scope_type] = 'tenant' AND [tenant_id] IS NOT NULL AND [user_id] IS NULL) OR
        ([scope_type] = 'user'   AND [tenant_id] IS NOT NULL AND [user_id] IS NOT NULL)
    ),
    CONSTRAINT [CK_report_saved_criteria_json] CHECK (ISJSON([criteria_json]) = 1);

-- name uniqueness per scope tier
CREATE UNIQUE INDEX [UQ_report_saved_criteria_system] ON [rpt].[report_saved_criteria] ([report_id], [criteria_name])
    WHERE [scope_type] = 'system' AND [is_deleted] = 0;
CREATE UNIQUE INDEX [UQ_report_saved_criteria_tenant] ON [rpt].[report_saved_criteria] ([report_id], [tenant_id], [criteria_name])
    WHERE [scope_type] = 'tenant' AND [is_deleted] = 0;
CREATE UNIQUE INDEX [UQ_report_saved_criteria_user] ON [rpt].[report_saved_criteria] ([report_id], [tenant_id], [user_id], [criteria_name])
    WHERE [scope_type] = 'user' AND [is_deleted] = 0;

-- at most one default per scope tier
CREATE UNIQUE INDEX [UQ_report_saved_criteria_system_default] ON [rpt].[report_saved_criteria] ([report_id])
    WHERE [scope_type] = 'system' AND [is_default] = 1 AND [is_deleted] = 0;
CREATE UNIQUE INDEX [UQ_report_saved_criteria_tenant_default] ON [rpt].[report_saved_criteria] ([report_id], [tenant_id])
    WHERE [scope_type] = 'tenant' AND [is_default] = 1 AND [is_deleted] = 0;
CREATE UNIQUE INDEX [UQ_report_saved_criteria_user_default] ON [rpt].[report_saved_criteria] ([report_id], [tenant_id], [user_id])
    WHERE [scope_type] = 'user' AND [is_default] = 1 AND [is_deleted] = 0;

CREATE NONCLUSTERED INDEX [IX_report_saved_criteria_tenant_id] ON [rpt].[report_saved_criteria] ([tenant_id], [is_deleted]);
CREATE NONCLUSTERED INDEX [IX_report_saved_criteria_report_id] ON [rpt].[report_saved_criteria] ([report_id]);


-- ============================================================================
-- 5. rpt.report_saved_layout — same scope pattern as report_saved_criteria
-- ============================================================================
-- Same app-layer tenant-consistency rule as report_saved_criteria above (not DB-enforced):
-- IF report_definition.scope_type = 'tenant' THEN this row's tenant_id MUST equal
-- report_definition.tenant_id. For a 'system' report, any tenant/user override is allowed.
CREATE TABLE [rpt].[report_saved_layout] (
    [id]                varchar(26)     NOT NULL,
    [tenant_id]         varchar(26)     NULL,        -- NULL only when scope_type = 'system'

    [report_id]         varchar(26)     NOT NULL,
    [scope_type]        varchar(10)     NOT NULL,    -- system / tenant / user
    [user_id]           varchar(26)     NULL,        -- required only when scope_type = 'user'
    [layout_name]       nvarchar(200)   NOT NULL,
    -- column order/visibility/width/group-by/sort. Always include a top-level "version" int
    -- so the app can migrate older saved layouts if the shape changes, e.g.
    -- {"version": 1, "columns": [...], "sort": [...], "group": [...]}
    [layout_json]       nvarchar(max)   NOT NULL,
    [is_default]        bit             NOT NULL,

    [is_active]         bit             NOT NULL,
    [is_deleted]        bit             NOT NULL,
    [row_version]       timestamp       NOT NULL,
    [created_at]        datetime2(3)    NOT NULL,
    [updated_at]        datetime2(3)    NOT NULL,
    [created_by]        varchar(26)     NULL,
    [updated_by]        varchar(26)     NULL,
    [deleted_by]        varchar(26)     NULL,

    CONSTRAINT [PK_report_saved_layout] PRIMARY KEY CLUSTERED ([id] ASC)
);

ALTER TABLE [rpt].[report_saved_layout] ADD
    CONSTRAINT [DF_report_saved_layout_is_default] DEFAULT ((0))              FOR [is_default],
    CONSTRAINT [DF_report_saved_layout_is_active]  DEFAULT ((1))              FOR [is_active],
    CONSTRAINT [DF_report_saved_layout_is_deleted] DEFAULT ((0))              FOR [is_deleted],
    CONSTRAINT [DF_report_saved_layout_created_at] DEFAULT (sysutcdatetime()) FOR [created_at],
    CONSTRAINT [DF_report_saved_layout_updated_at] DEFAULT (sysutcdatetime()) FOR [updated_at];

ALTER TABLE [rpt].[report_saved_layout] WITH CHECK ADD
    CONSTRAINT [FK_report_saved_layout_report_id]  FOREIGN KEY ([report_id])  REFERENCES [rpt].[report_definition] ([id]),
    CONSTRAINT [FK_report_saved_layout_tenant_id]  FOREIGN KEY ([tenant_id])  REFERENCES [tenant].[tenant] ([id]),
    CONSTRAINT [FK_report_saved_layout_user_id]    FOREIGN KEY ([user_id])    REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_saved_layout_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_saved_layout_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user] ([id]),
    CONSTRAINT [FK_report_saved_layout_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user] ([id]);

ALTER TABLE [rpt].[report_saved_layout] WITH CHECK ADD
    CONSTRAINT [CK_report_saved_layout_scope] CHECK (
        ([scope_type] = 'system' AND [tenant_id] IS NULL     AND [user_id] IS NULL) OR
        ([scope_type] = 'tenant' AND [tenant_id] IS NOT NULL AND [user_id] IS NULL) OR
        ([scope_type] = 'user'   AND [tenant_id] IS NOT NULL AND [user_id] IS NOT NULL)
    ),
    CONSTRAINT [CK_report_saved_layout_json] CHECK (ISJSON([layout_json]) = 1);

CREATE UNIQUE INDEX [UQ_report_saved_layout_system] ON [rpt].[report_saved_layout] ([report_id], [layout_name])
    WHERE [scope_type] = 'system' AND [is_deleted] = 0;
CREATE UNIQUE INDEX [UQ_report_saved_layout_tenant] ON [rpt].[report_saved_layout] ([report_id], [tenant_id], [layout_name])
    WHERE [scope_type] = 'tenant' AND [is_deleted] = 0;
CREATE UNIQUE INDEX [UQ_report_saved_layout_user] ON [rpt].[report_saved_layout] ([report_id], [tenant_id], [user_id], [layout_name])
    WHERE [scope_type] = 'user' AND [is_deleted] = 0;

CREATE UNIQUE INDEX [UQ_report_saved_layout_system_default] ON [rpt].[report_saved_layout] ([report_id])
    WHERE [scope_type] = 'system' AND [is_default] = 1 AND [is_deleted] = 0;
CREATE UNIQUE INDEX [UQ_report_saved_layout_tenant_default] ON [rpt].[report_saved_layout] ([report_id], [tenant_id])
    WHERE [scope_type] = 'tenant' AND [is_default] = 1 AND [is_deleted] = 0;
CREATE UNIQUE INDEX [UQ_report_saved_layout_user_default] ON [rpt].[report_saved_layout] ([report_id], [tenant_id], [user_id])
    WHERE [scope_type] = 'user' AND [is_default] = 1 AND [is_deleted] = 0;

CREATE NONCLUSTERED INDEX [IX_report_saved_layout_tenant_id] ON [rpt].[report_saved_layout] ([tenant_id], [is_deleted]);
CREATE NONCLUSTERED INDEX [IX_report_saved_layout_report_id] ON [rpt].[report_saved_layout] ([report_id]);
