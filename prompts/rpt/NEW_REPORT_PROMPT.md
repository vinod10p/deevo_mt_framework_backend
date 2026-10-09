# Prompt — Add a new report to the generic report writer (`rpt`)

Use this to create a report for the generic report writer (`mtf/rpt`). Paste the whole file into
the AI tool, then describe the report in the **Request** block below. The output is **one SQL
script**: stored procedure(s) plus catalog metadata rows. No Python, API, or React changes are
needed — the catalog, criteria panel, grid, lookups, and saved views are all driven by the rows you
insert.

Background: `prompts/rpt/REPORT_API_PROMPT.md` ("Stored procedure contract"),
`docs/rpt_schema_v5.sql` (DDL), `docs/rpt_seed_sample_report.sql` (five working examples).

---

## Request (fill this in)

```text
Report name (display):   e.g. "Accounts by Month"
report_key:              e.g. tenant_account_monthly   (lowercase snake_case, ≤ 100 chars, stable)
Scope:                   system (every tenant)  |  tenant (one tenant's custom report: give tenant_id)
Purpose / description:   one sentence shown in the catalog (≤ 500 chars)
Source tables:           e.g. tenant.tenant_account
Output columns:          name, meaning, type; which are visible by default, groupable, summed …
Filters (criteria):      name, input type, required?, default, dropdown source
Row cap:                 default_max_rows (default 20000; lower for aggregated reports)
Built-in views (opt.):   named starting layouts every user sees
Target repo / file:      framework sample → docs/; product report → that product's sql/ folder
```

---

## 1. What a report is made of

| Piece | Where | Required |
|---|---|---|
| Report proc — returns the rows | `rpt.usp_<report_key>` (any `schema.name` works) | yes |
| Lookup proc(s) — dropdown options | `rpt.usp_lookup_<thing>`; reuse existing ones when possible | only for `dropdown` / `multiselect` criteria |
| `rpt.report_definition` | 1 row: key, name, proc, scope, row cap | yes |
| `rpt.report_column` | 1 row per output column of the proc | yes |
| `rpt.report_criteria` | 1 row per filter field | no (a report may have no criteria) |
| `rpt.report_saved_view` | `system` rows = built-in views | no |

Execution path, for orientation: the API reads the tenant from the JWT and sets
`SESSION_CONTEXT(N'tenant_id')`; resolves `report_key` → `report_definition`; validates the
client's criteria against `report_criteria`; calls
`EXEC <proc_name> @CriteriaJson = ?, @MaxRows = ?`; checks the result's column names equal the
active `report_column` names; encodes each value by `report_column.data_type`.

---

## 2. Decide first

- **Scope.** `system` = one row, visible to every tenant, `tenant_id` NULL. `tenant` = visible only
  to that tenant, `tenant_id` set; a tenant report with the same `report_key` as a system report
  replaces it for that tenant.
- **Where the script lives.** Framework-level reports over `auth` / `tenant` tables:
  `docs/rpt_seed_sample_report.sql` (or a new `docs/rpt_seed_<name>.sql`). Product reports (CRM,
  invoices, …): the product repo, e.g. `sql/rpt_<product>_reports.sql`.
- **Proc schema.** Put procs in `rpt`. `GRANT EXECUTE ON SCHEMA::rpt TO deevo_app` (in the sample
  seed) already covers them. A proc in another schema needs its own
  `GRANT EXECUTE ON <schema>.<proc> TO deevo_app;`.
- **IDs.** Every `id` is `varchar(26)`, ULID format (Crockford base32: digits and uppercase letters
  except I, L, O, U). Seed scripts use a readable fixed prefix so re-runs can find their own rows:
  `01JRPT` + 3-letter app code + table code + zero-padded number, total 26 chars.

  | Table | Example id |
  |---|---|
  | report_definition | `01JRPTEXMDF000000000000001` |
  | report_column | `01JRPTEXMCM000000000000101` |
  | report_criteria | `01JRPTEXMCR000000000000101` |
  | report_saved_view | `01JRPTEXMSV000000000000101` |

  Existing prefixes: `01JRPTMTF` (framework samples), `01JRPTDVF` (DeevoFlow). Pick a new app code
  per script. Real ULIDs (`uv run python -c "from ulid import ULID; print(ULID())"`) also work.

---

## 3. Report proc contract

```sql
CREATE OR ALTER PROCEDURE rpt.usp_<report_key>
    @CriteriaJson nvarchar(max),
    @MaxRows      int
AS
```

Rules — the API enforces or depends on every one:

1. **Exactly these two parameters**, named exactly like this.
2. **Tenant from session context, never a parameter.** First statements:
   `DECLARE @TenantId varchar(26) = CAST(SESSION_CONTEXT(N'tenant_id') AS varchar(26));`
   `IF @TenantId IS NULL THROW 50001, 'Tenant session context is not set.', 1;`
   Filter every tenant-owned table by `@TenantId`. (`SESSION_CONTEXT(N'user_id')` is also set.)
3. **A criterion missing from the JSON means "no filter".** The API drops empty values and does
   **not** apply `default_value` (that is only the UI's initial value), so `{}` must return the
   unfiltered result.
4. **Final `SELECT TOP (@MaxRows + 1)`.** The extra row is how the API detects `truncated`; never
   use `TOP (@MaxRows)` and never page.
5. **Exactly one result set whose column names equal the report's active `report_column.column_name`
   values** — no extra, no missing, no duplicates (order doesn't matter). A mismatch is a `500
   REPORT_EXECUTION_FAILED`. Use `SET NOCOUNT ON`.
6. **Values must fit the column's `data_type`** (§5.2). Convert `uniqueidentifier`, `xml`, etc. to
   strings in the proc; store/return datetimes in UTC.
7. Read-only: no writes, no temp state left behind. Must finish within the API timeout
   (`DEEVO_REPORT_QUERY_TIMEOUT_SECONDS`, default 60 s) — index the filter columns.

### Reading criteria in T-SQL

The API sends the **validated, normalized** criteria as a JSON object keyed by `criteria_key`.

| `control_type` / `data_type` | JSON the proc receives | T-SQL |
|---|---|---|
| `text` / `string` | `"abc"` | `JSON_VALUE(@CriteriaJson, '$.k')` |
| `number` / `int` | `42` | `TRY_CAST(JSON_VALUE(@CriteriaJson, '$.k') AS int)` |
| `number` / `decimal` | `10.5` (exact) | `TRY_CAST(JSON_VALUE(@CriteriaJson, '$.k') AS decimal(19, 4))` |
| `date` / `date` | `"2026-01-31"` | `TRY_CAST(JSON_VALUE(@CriteriaJson, '$.k') AS date)` |
| `date` / `datetime` | `"2026-01-31T09:00:00"` (UTC, no offset) | `TRY_CAST(JSON_VALUE(@CriteriaJson, '$.k') AS datetime2(3))` |
| `daterange` | `{"from": "…", "to": "…"}` — either key may be **absent** | `'$.k.from'` and `'$.k.to'` separately |
| `dropdown` | one scalar of its `data_type` | same as the scalar rows above |
| `multiselect` | `["a", "b"]` (de-duplicated) | `OPENJSON(@CriteriaJson, '$.k')` into a table variable |
| `bool` | `true` / `false` | `TRY_CAST(JSON_VALUE(@CriteriaJson, '$.k') AS bit)` |

Patterns:

```sql
-- inclusive date range on a datetime column
AND (@From IS NULL OR t.created_at >= @From)
AND (@To   IS NULL OR t.created_at <  DATEADD(day, 1, @To))

-- multiselect: empty list = no filter
DECLARE @Types TABLE (v nvarchar(50) PRIMARY KEY);
INSERT INTO @Types (v) SELECT DISTINCT j.[value] FROM OPENJSON(@CriteriaJson, '$.account_type') AS j
WHERE j.[value] IS NOT NULL;
AND (NOT EXISTS (SELECT 1 FROM @Types) OR t.account_type IN (SELECT v FROM @Types))
```

**Bool semantics — pick one per criterion and name it accordingly.** The UI offers Any (key absent)
/ Yes (`true`) / No (`false`).
- *"X only"* flag (`default_only`, `overdue_only`): `false` and absent both mean no filter —
  `AND (ISNULL(@Flag, 0) = 0 OR t.flag = 1)`.
- *Value match* (`is_active`): `false` is a real filter (inactive only) —
  `AND (@IsActive IS NULL OR t.is_active = @IsActive)`.

---

## 4. Lookup proc contract (dropdown / multiselect options)

Reuse an existing lookup when it fits (`rpt.usp_lookup_account_type`, `usp_lookup_account_status`,
`usp_lookup_account`, `usp_lookup_address_type`, `usp_lookup_tenant_user_role`,
`usp_lookup_portal_user_role`). Otherwise:

```sql
CREATE OR ALTER PROCEDURE rpt.usp_lookup_<thing>
    @SearchText nvarchar(200) = NULL,   -- user's typed text; match on the label
    @Values     nvarchar(max) = NULL,   -- JSON array of value strings: resolve labels for these
    @MaxRows    int           = 50
AS
```

- Return **exactly two columns named `value` and `label`**. The API sends `value` to the client as
  a string and skips rows where it is NULL; return it already as the exact text the report proc
  expects (`CONVERT(nvarchar(26), id)`, not a `decimal` that would render as `1.00`).
- `SELECT TOP (@MaxRows + 1)` (drives `has_more`), stable `ORDER BY`.
- Honour both filters: `(@SearchText IS NULL OR label LIKE N'%' + @SearchText + N'%')` and
  `(@Values IS NULL OR value IN (SELECT [value] FROM OPENJSON(@Values)))`.
- Tenant data → read `SESSION_CONTEXT(N'tenant_id')` and `THROW` if NULL, like report procs. A fixed
  list (statuses, roles) can be a `VALUES` table and needs no tenant.
- `value` is exactly what the report proc receives for that criterion.

---

## 5. Metadata rows — table by table

Leave the audit block to defaults: `is_active` (1), `is_deleted` (0), `created_at`/`updated_at`
(`sysutcdatetime()`), `row_version` (automatic); `created_by`/`updated_by`/`deleted_by` may be NULL.

### 5.1 `rpt.report_definition` — one row

| Column | Value | Rules |
|---|---|---|
| `id` | ULID | |
| `tenant_id` | `NULL` for `system`; the tenant's id for `tenant` | `CK_report_definition_scope`; FK to `tenant.tenant` |
| `scope_type` | `'system'` / `'tenant'` | |
| `report_key` | `'tenant_account_monthly'` | unique among live system reports / per tenant; used in URLs — never rename |
| `display_name` | `N'Accounts by Month'` | ≤ 200 |
| `proc_name` | `'rpt.usp_tenant_account_monthly'` | must be `schema.name` (letters, digits, `_`) — anything else fails at run time |
| `description` | `N'…'` | ≤ 500, shown in the catalog |
| `default_max_rows` | `20000` | hard cap for `/run` (clients may ask for fewer, never more) |

### 5.2 `rpt.report_column` — one row per proc output column

| Column | Meaning / allowed values |
|---|---|
| `report_id` | the definition's `id` |
| `column_name` | **exactly** the proc's output column name; unique per report; also the key in every JSON row |
| `display_name` | grid header |
| `data_type` | `string` · `int` · `decimal` · `date` · `datetime` · `bool` — see mapping below |
| `display_order` | 10, 20, 30 … (default column order and picker order) |
| `is_displayable` | 0 = never shown as a grid column (value still returned) |
| `is_default_visible` | shown before any saved view is applied |
| `is_sortable` / `is_groupable` | grid sort / group-by allowed |
| `is_filterable` | client-side column filter on loaded rows (not a criterion) |
| `is_aggregatable` | can be subtotalled in grouped mode |
| `default_aggregate_type` | `sum` · `avg` · `count` · `min` · `max` · NULL |
| `display_format` | `currency` · `currency:EUR` · `percent` (value already 0–100) · `MM/dd/yyyy` · NULL |
| `default_width` | px, NULL → 150 |

Check constraints: `is_displayable = 0` requires `is_default_visible = is_sortable = is_groupable = 0`;
`is_aggregatable = 0` requires `default_aggregate_type IS NULL`.

SQL type → `data_type`: `varchar`/`nvarchar`/`char` → `string`; `int`/`smallint`/`tinyint`/`bigint`
→ `int` (JavaScript loses precision above 2^53); `decimal`/`numeric`/`money`/`float` → `decimal`;
`date` → `date`; `datetime2`/`datetime` (UTC) → `datetime`; `bit` → `bool`.

### 5.3 `rpt.report_criteria` — one row per filter field

| Column | Meaning / allowed values |
|---|---|
| `report_id` | the definition's `id` |
| `criteria_key` | JSON key the proc reads (`'$.<criteria_key>'`); unique per report |
| `display_name` | field label |
| `control_type` | `text` · `number` · `date` · `daterange` · `dropdown` · `multiselect` · `bool` |
| `data_type` | type of the collected value(s) |
| `lookup_proc` | `schema.name` of a lookup proc — **set for every `dropdown` / `multiselect`**, NULL otherwise |
| `default_value` | literal initial UI value or NULL — keep it scalar: `N'active'`, `N'true'` / `N'false'`, `N'25'`, `N'2026-01-01'`; leave NULL for `multiselect` / `daterange`; tokens like `@today` are **not** supported |
| `is_required` | 1 → the API returns 422 when it's empty; the UI blocks Run |
| `display_order` | 10, 20, 30 … |

Allowed pairings (`CK_report_criteria_control_data`): `bool` ↔ `bool`; `date`/`daterange` ↔ `date`
or `datetime`; `number` ↔ `int` or `decimal`; `text`/`dropdown`/`multiselect` ↔ any type.

### 5.4 `rpt.report_saved_view` — optional built-in views

Only `scope_type = 'system'` rows belong in scripts (tenant and user views are created in the app).
System views are allowed **only on system reports** — an app-layer rule the database does not
enforce. A script also bypasses the API's layout validation, so follow the rules below exactly.

| Column | Value |
|---|---|
| `tenant_id`, `user_id` | NULL |
| `scope_type` | `'system'` |
| `view_name` | unique per report among system views |
| `criteria_json` | `N'{"version":1, …}'` — criteria in the §3 normalized shapes, keys = current `criteria_key`s |
| `layout_json` | `N'{"version":1,"columns":[…],"sort":[…],"group":[…],"aggregates":[]}'` |
| `is_default` | 1 for at most one system view per report (applied when the user has no personal/tenant default) |

Layout entries: `columns` = `{"column_name","visible","width"}` in display order (only displayable
columns may be `visible: true`); `sort` = `{"column_name","direction":"asc"|"desc"}` (sortable
columns); `group` = groupable `column_name`s; `aggregates` = `{"column_name","type"}`
(aggregatable). Both JSON documents **must** contain `"version": 1`.

---

## 6. Script layout

```sql
-- header: what, which DB, run as deevo_ddl, safe to re-run
-- 1. lookup procs      (CREATE OR ALTER … GO)
-- 2. report proc(s)    (CREATE OR ALTER … GO)
-- 3. metadata          (SET XACT_ABORT ON; BEGIN TRANSACTION … COMMIT)
--      delete this script's rows by id prefix / report_key (children first)
--      insert definition → columns → criteria → system saved views
```

Delete order is `report_saved_view` → `report_criteria` → `report_column` → `report_definition`
(foreign keys, no cascade). Hard delete is acceptable **only** in seed scripts for rows the script
owns.

**Production caution.** Delete-and-reinsert also deletes every user's saved views on that report.
Once a report is live, change it with targeted `UPDATE`s / `INSERT`s instead, and retire a column or
criterion with `is_deleted = 1` (soft delete), so saved views survive. Removing or renaming a
`column_name` / `criteria_key` makes saved views drop that setting — the UI tolerates it, but users
lose it.

A `tenant` report must guard its insert:
`IF EXISTS (SELECT 1 FROM tenant.tenant WHERE id = @TenantId) BEGIN … END` (FK).

---

## 7. Worked example — `tenant_account_monthly` (system report)

New accounts per month and account type, with the active share. Reuses the existing
`rpt.usp_lookup_account_type`. The proc body has been run against the dev database.

```sql
-- ============================================================================
-- rpt report: tenant_account_monthly — Accounts by Month
-- Run in SSMS as deevo_ddl. Safe to re-run (rows with id prefix 01JRPTEXM are replaced).
-- ============================================================================

-- {"account_type": ["customer"], "created_date": {"from": "2026-01-01"},
--  "min_accounts": 2, "active_only": true}
CREATE OR ALTER PROCEDURE rpt.usp_tenant_account_monthly
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
    DECLARE @MinAccounts int  = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.min_accounts') AS int);
    DECLARE @ActiveOnly  bit  = TRY_CAST(JSON_VALUE(@CriteriaJson, '$.active_only')  AS bit);

    DECLARE @AccountTypes TABLE (account_type nvarchar(50) PRIMARY KEY);
    INSERT INTO @AccountTypes (account_type)
    SELECT DISTINCT j.[value]
    FROM OPENJSON(@CriteriaJson, '$.account_type') AS j
    WHERE j.[value] IS NOT NULL;

    SELECT TOP (@MaxRows + 1)
        DATEFROMPARTS(YEAR(a.created_at), MONTH(a.created_at), 1)        AS created_month,
        a.account_type,
        COUNT(*)                                                          AS account_count,
        SUM(CASE WHEN a.is_active = 1 THEN 1 ELSE 0 END)                  AS active_count,
        CAST(100.0 * SUM(CASE WHEN a.is_active = 1 THEN 1 ELSE 0 END) / COUNT(*)
             AS decimal(5, 1))                                            AS active_pct
    FROM tenant.tenant_account AS a
    WHERE a.tenant_id = @TenantId
      AND a.is_deleted = 0
      AND (@CreatedFrom IS NULL OR a.created_at >= @CreatedFrom)
      AND (@CreatedTo   IS NULL OR a.created_at <  DATEADD(day, 1, @CreatedTo))
      AND (ISNULL(@ActiveOnly, 0) = 0 OR a.is_active = 1)
      AND (NOT EXISTS (SELECT 1 FROM @AccountTypes)
           OR a.account_type IN (SELECT account_type FROM @AccountTypes))
    GROUP BY DATEFROMPARTS(YEAR(a.created_at), MONTH(a.created_at), 1), a.account_type
    HAVING (@MinAccounts IS NULL OR COUNT(*) >= @MinAccounts)
    ORDER BY created_month DESC, a.account_type;
END
GO

SET XACT_ABORT ON;
BEGIN TRANSACTION;

DECLARE @R varchar(26) = '01JRPTEXMDF000000000000001';

DELETE FROM rpt.report_saved_view
WHERE report_id IN (SELECT id FROM rpt.report_definition
                    WHERE id LIKE '01JRPTEXM%'
                       OR (scope_type = 'system' AND report_key = 'tenant_account_monthly'));
DELETE FROM rpt.report_criteria
WHERE report_id IN (SELECT id FROM rpt.report_definition
                    WHERE id LIKE '01JRPTEXM%'
                       OR (scope_type = 'system' AND report_key = 'tenant_account_monthly'));
DELETE FROM rpt.report_column
WHERE report_id IN (SELECT id FROM rpt.report_definition
                    WHERE id LIKE '01JRPTEXM%'
                       OR (scope_type = 'system' AND report_key = 'tenant_account_monthly'));
DELETE FROM rpt.report_definition
WHERE id LIKE '01JRPTEXM%'
   OR (scope_type = 'system' AND report_key = 'tenant_account_monthly');

INSERT INTO rpt.report_definition
    (id, tenant_id, scope_type, report_key, display_name, proc_name, description, default_max_rows)
VALUES
    (@R, NULL, 'system', 'tenant_account_monthly', N'Accounts by Month',
     'rpt.usp_tenant_account_monthly',
     N'New accounts per month and account type, with the share that is active.', 5000);

INSERT INTO rpt.report_column
    (id, report_id, column_name, display_name, data_type, display_order,
     is_displayable, is_default_visible, is_sortable, is_groupable, is_filterable,
     is_aggregatable, default_aggregate_type, display_format, default_width)
VALUES
    ('01JRPTEXMCM000000000000101', @R, 'created_month', N'Month',    'date',    10, 1, 1, 1, 1, 1, 0, NULL,    'MM/dd/yyyy', 120),
    ('01JRPTEXMCM000000000000102', @R, 'account_type',  N'Type',     'string',  20, 1, 1, 1, 1, 1, 1, 'count', NULL,         120),
    ('01JRPTEXMCM000000000000103', @R, 'account_count', N'Accounts', 'int',     30, 1, 1, 1, 0, 1, 1, 'sum',   NULL,         110),
    ('01JRPTEXMCM000000000000104', @R, 'active_count',  N'Active',   'int',     40, 1, 1, 1, 0, 1, 1, 'sum',   NULL,         110),
    ('01JRPTEXMCM000000000000105', @R, 'active_pct',    N'Active %', 'decimal', 50, 1, 1, 1, 0, 1, 0, NULL,    'percent',    100);

INSERT INTO rpt.report_criteria
    (id, report_id, criteria_key, display_name, data_type, control_type,
     lookup_proc, default_value, is_required, display_order)
VALUES
    ('01JRPTEXMCR000000000000101', @R, 'account_type', N'Account Type', 'string', 'multiselect',
     'rpt.usp_lookup_account_type', NULL,     0, 10),
    ('01JRPTEXMCR000000000000102', @R, 'created_date', N'Created Date', 'date',   'daterange',
     NULL,                          NULL,     0, 20),
    ('01JRPTEXMCR000000000000103', @R, 'min_accounts', N'Min Accounts', 'int',    'number',
     NULL,                          NULL,     0, 30),
    ('01JRPTEXMCR000000000000104', @R, 'active_only',  N'Active Only',  'bool',   'bool',
     NULL,                          N'false', 0, 40);

-- built-in view: customers only, grouped by type, newest month first
INSERT INTO rpt.report_saved_view
    (id, tenant_id, report_id, scope_type, user_id, view_name, criteria_json, layout_json, is_default)
VALUES
    ('01JRPTEXMSV000000000000101', NULL, @R, 'system', NULL, N'Customers by month',
     N'{"version":1,"account_type":["customer"]}',
     N'{"version":1,
        "columns":[{"column_name":"created_month","visible":true,"width":null},
                   {"column_name":"account_type","visible":true,"width":null},
                   {"column_name":"account_count","visible":true,"width":null},
                   {"column_name":"active_count","visible":true,"width":null},
                   {"column_name":"active_pct","visible":false,"width":null}],
        "sort":[{"column_name":"created_month","direction":"desc"}],
        "group":["account_type"],
        "aggregates":[]}',
     0);

COMMIT TRANSACTION;
GO
```

---

## 8. Verify

1. **Run the proc directly** (SSMS, as any login that can execute it):

   ```sql
   EXEC sp_set_session_context @key = N'tenant_id', @value = '<tenant id>';
   EXEC rpt.usp_tenant_account_monthly @CriteriaJson = N'{}', @MaxRows = 100;
   EXEC rpt.usp_tenant_account_monthly @CriteriaJson = N'{"account_type":["customer"],"active_only":true}', @MaxRows = 100;
   EXEC rpt.usp_tenant_account_monthly @CriteriaJson = N'{}', @MaxRows = 1;   -- returns 2 rows if ≥ 2 exist
   ```

2. **Column contract** — must return no rows:

   ```sql
   DECLARE @ReportKey varchar(100) = 'tenant_account_monthly';
   DECLARE @ReportId varchar(26), @Proc varchar(256);
   SELECT @ReportId = id, @Proc = proc_name FROM rpt.report_definition
   WHERE report_key = @ReportKey AND scope_type = 'system' AND is_deleted = 0;

   SELECT 'missing_from_proc' AS problem, c.column_name AS name
   FROM rpt.report_column AS c
   WHERE c.report_id = @ReportId AND c.is_deleted = 0 AND c.is_active = 1
     AND c.column_name NOT IN (SELECT r.name FROM sys.dm_exec_describe_first_result_set_for_object(OBJECT_ID(@Proc), 0) AS r WHERE r.name IS NOT NULL)
   UNION ALL
   SELECT 'not_in_metadata', r.name
   FROM sys.dm_exec_describe_first_result_set_for_object(OBJECT_ID(@Proc), 0) AS r
   WHERE r.name NOT IN (SELECT c.column_name FROM rpt.report_column AS c
                        WHERE c.report_id = @ReportId AND c.is_deleted = 0 AND c.is_active = 1);
   ```

   (If the proc uses `#temp` tables, `dm_exec_describe_first_result_set_for_object` can't describe
   it — compare against the columns from step 1 instead.)

3. **Through the API** (tenant JWT; prefix is the host app's mount, e.g. `/api` or `/api/v1`):
   `GET …/reports` lists it · `GET …/reports/tenant_account_monthly` shows columns and criteria ·
   `POST …/reports/tenant_account_monthly/run` with `{}` returns rows · each lookup returns options ·
   `GET …/reports/tenant_account_monthly/views` shows the built-in view.

4. Framework sample reports only: add representative criteria to `SAMPLE_CRITERIA` in
   `tests/rpt/test_seeded_reports_integration.py` and run `uv run pytest tests/rpt -m integration`.

5. Apply the script to **every** database that serves the app (local dev, office dev, Azure).

---

## 9. Common mistakes

| Mistake | Symptom |
|---|---|
| Proc column name ≠ `report_column.column_name` (typo, alias missing, extra column) | `500 REPORT_EXECUTION_FAILED` on every run |
| `TOP (@MaxRows)` instead of `TOP (@MaxRows + 1)` | `truncated` / `has_more` never true |
| Treating a missing criterion as "match nothing" | `{}` returns no rows |
| Expecting `default_value` to be sent | proc filters wrong when the user clears the field |
| `dropdown` / `multiselect` without `lookup_proc` | field has no options |
| Lookup columns not named exactly `value` / `label` | lookup `500` |
| Tenant data read without the `SESSION_CONTEXT` filter | cross-tenant data leak |
| `proc_name` not `schema.name` (brackets, spaces, three parts) | run fails |
| `is_displayable = 0` with `is_sortable = 1`, or `default_aggregate_type` on a non-aggregatable column | insert fails (check constraint) |
| `control_type = 'number'` with `data_type = 'string'` | insert fails (check constraint) |
| Saved view JSON without `"version": 1` | insert fails (check constraint) |
| `system` view on a tenant report | insert succeeds but breaks the app's view rules — don't |
| Re-running a delete-and-insert script in production | users' saved views on the report are deleted |
| Proc outside `rpt` without `GRANT EXECUTE` | run fails with a permission error |
