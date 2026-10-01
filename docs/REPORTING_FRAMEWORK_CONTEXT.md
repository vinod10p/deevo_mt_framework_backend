# Generic Reporting Framework — Project Context

Read this before writing or editing any code in this project. It explains what the framework
is, why the database is shaped the way it is, and the rules that keep "generic" actually
generic as new reports get added. The SQL in this folder (`rpt_schema_v2.sql`) is the source
of truth for exact DDL — this document explains the *why* behind it and the architecture that
sits on top of it.

## 1. What this is

A metadata-driven reporting framework for Deevolight's multi-tenant SaaS platform. The core
idea: **all report-specific business logic lives inside a single SQL Server stored procedure
per report.** Everything else — the filter panel, column layout, grouping, totals, saved
views — is generic and driven entirely by metadata tables. Adding a new report should mean
writing one new stored procedure plus a handful of new metadata rows, and **touching zero
backend or frontend application code.**

This is a module within the broader Deevolight platform (single shared database, multiple
tenants), reusing the same `auth`, `tenant`, and `audit` schemas, database standards, and
backend conventions already established for DeevoAgent — not a standalone product with its
own auth/tenant model.

## 2. The `rpt` schema — five tables

All DDL is in `rpt_schema_v2.sql`. Summary of what each table is for and the non-obvious
design decisions behind it:

### `report_definition` — the report registry
One row per report. Key columns: `report_key` (stable public identifier used in API calls,
e.g. `'SalesByRegion'`), `proc_name` (the stored proc to call, e.g. `'rpt.usp_sales_by_region'`),
`default_max_rows` (passed to the proc as a safety governor — there is **no pagination** in
this framework; clients are small/medium businesses and the whole filtered result set loads
into the browser grid at once).

`scope_type` (`'system'` or `'tenant'`) paired with a nullable `tenant_id` says whether a
report is platform-wide or owned by one tenant. `tenant_id` is `NULL` only when
`scope_type = 'system'` — this pairing is enforced by `CK_report_definition_scope`, so the
meaning is never left to be inferred from `NULL` alone.

### `report_column` — what the grid can display
One row per column the report proc's result set can produce. **Deliberately has no
`tenant_id` column** — it's fully derived via `report_id -> report_definition.tenant_id`
and was removed from an earlier version after review. Two reasons: it was pure redundancy
(a column has no tenant identity independent of its report), and more importantly, the
composite FK that used to enforce it had a real bug — **SQL Server only supports
`MATCH SIMPLE` for multi-column foreign keys: if any one column in the composite is `NULL`,
the entire constraint is skipped for that row.** Every column belonging to a system-wide
report has `tenant_id = NULL`, so that FK was silently failing to validate `report_id`
existed at all for those rows. Don't reintroduce a composite FK like that anywhere in this
schema.

Six independent behavior flags drive the grid, all orthogonal to each other:

| Flag | Meaning |
|---|---|
| `is_displayable` | Can this column ever appear as a grid column at all |
| `is_default_visible` | Shown by default (only meaningful if `is_displayable = 1`) |
| `is_sortable` | Header-click sortable (only meaningful if `is_displayable = 1`) |
| `is_groupable` | Draggable into group-by (only meaningful if `is_displayable = 1`) |
| `is_filterable` | Shows up in the **in-grid, client-side** column filter picker — independent of `is_displayable` |
| `is_aggregatable` | Can be summarized in a group footer/total row; `default_aggregate_type` (`sum`/`avg`/`count`/`min`/`max`) is the initial pick, changeable by the user in-grid |

A column can be `is_displayable = 0, is_filterable = 1` — never shown in the grid, but still
usable to filter unambiguously (e.g. filtering by `CustomerId` while only `CustomerName` is
displayed). Two `CHECK` constraints keep these flags internally consistent — don't bypass
them at the application layer.

`display_format` (not `format` — renamed for consistency with `display_name`/`display_order`)
holds named formats like `'currency'`, `'percent'`, `'MM/dd/yyyy'`. `default_width` is the
initial grid column width in px; a saved layout can override it per user.

### `report_criteria` — the pre-run filter panel
One row per field rendered in the filter panel the user fills in **before** running the
report. Same no-`tenant_id` rationale as `report_column`.

**This is a completely different filtering mechanism from `report_column.is_filterable`.**
`report_criteria` builds `@CriteriaJson`, sent to the stored proc, before it runs — it can
reference things that are never displayed (e.g. an `asOfDate` criterion that changes how an
aging report calculates its buckets, with no matching grid column). `report_column.is_filterable`
is a client-side filter applied to rows already loaded in the browser, after the proc has
already run, and never touches the server again. Don't conflate the two.

Two columns on each criterion: `control_type` (which input widget to render — `text`,
`number`, `date`, `daterange`, `dropdown`, `multiselect`, `bool`) and `data_type` (the type
of the value once collected, driving how it's JSON-encoded). These are independent —
a `dropdown` can carry `int` values (a region ID) or `string` values (a status code) — but
`CK_report_criteria_control_data` enforces the pairings that are never sensible (a `bool`
control must carry `bool` data, etc.).

**JSON value-shape convention** (not schema-enforced, must be followed in code): the shape
of the value under `criteria_key` in `@CriteriaJson` depends on `control_type` —
- scalar for `text`/`number`/`date`/`dropdown`/`bool`
- array for `multiselect`
- `{"from": ..., "to": ...}` object for `daterange`

e.g. `{"invoice_date": {"from": "2026-01-01", "to": "2026-01-31"}, "status": "Open"}`.
`OPENJSON`'s `WITH` clause reads nested paths natively (`'$.invoice_date.from'`), so this
needs no special-casing in SQL. This keeps the "one row = one rendered filter field"
invariant even for range controls.

**`lookup_proc` contract**: every lookup proc (used to populate `dropdown`/`multiselect`
options) must return exactly two columns named `value` and `label` — never per-proc column
names. This is what keeps the front-end dropdown component fully generic.

**`default_value` convention**: literal values (`'Open'`, `'US'`) store as-is. Reserve
`@today`, `@month_start`, `@year_start`, `@current_user`, `@current_tenant` as dynamic
expressions resolved by the application layer at render time — not implemented yet, but the
column needs no schema change to support it later.

### `report_saved_criteria` / `report_saved_layout` — saved presets
Saved filter-panel values and saved grid layouts (column order/visibility/width/group-by/sort),
each with identical **System / Tenant / User** scoping:

- `scope_type = 'system'`: `tenant_id` and `user_id` both `NULL` — the platform default, not
  editable by a tenant
- `scope_type = 'tenant'`: `tenant_id` set, `user_id` `NULL` — visible to every user in that
  tenant
- `scope_type = 'user'`: both set — visible only to that one user

Enforced by `CK_..._scope`. Filtered unique indexes guarantee at most one `is_default = 1`
row per scope tier per report. When resolving the *effective* default for a user opening a
report, fall back User → Tenant → System (most specific wins).

Both `..._json` columns must always include a top-level `"version"` int
(e.g. `{"version": 1, "columns": [...], "sort": [...], "group": [...]}`) so the application
can migrate older saved rows if the shape changes later — this is a convention inside the
JSON payload, not a schema column.

**Unenforced-by-design rule, must live in the service layer with a test**: if the parent
report's `scope_type = 'tenant'`, a saved criteria/layout row's `tenant_id` must equal that
report's own `tenant_id` — a tenant should never be able to save a view against another
tenant's custom report. For a `'system'` report, any tenant/user override is allowed. This
isn't a `CHECK` constraint because expressing it would require a cross-table scalar UDF,
which hurts write performance — it's an explicit application-layer validation instead.

## 3. Backend architecture — two data-access strategies, not one

The backend has two fundamentally different problems and should not try to solve them with
one tool:

**Catalog services** — CRUD/read access to the five `rpt` tables above. Known, fixed shape.
Use **SQLModel**, same as the DeevoAgent backend, so ULID generation, soft-delete helpers,
`row_version` optimistic-concurrency checks, and audit-log-on-mutation can be shared
base-repository code rather than reinvented.

**Execution engine** — calls an *arbitrary* stored procedure by name and gets back an
*unknown-until-runtime* result shape. An ORM actively gets in the way here. Use a thin,
parameterized `pyodbc` wrapper: resolve `proc_name` from `report_definition`, call it with
bound parameters, read back whatever columns come out, return rows as plain dicts alongside
the already-known `report_column` metadata from the catalog (no need to re-derive column
shape from the query result).

Stack otherwise matches DeevoAgent: **FastAPI**, Pydantic v2, SQL Server via `pyodbc`,
ULID `varchar(26)` PKs, soft deletes, JWT auth with scope-based authorization
(`system`/`tenant`/`tenant_account` levels), hexagonal/layered structure.

### Catalog authoring for V1: developer-authored, not an admin UI

`report_definition`/`report_column`/`report_criteria` are tightly coupled to a specific
proc's actual contract — `column_name` must match the proc's output, `criteria_key` must
match what the proc's `OPENJSON` expects. Treat a report and its metadata as one deployable
unit for V1: **author new reports via SQL script/migration alongside the proc itself**, not
through a runtime admin CRUD API. The backend only needs *read* endpoints for these three
tables (to serve metadata to the frontend). `report_saved_criteria`/`report_saved_layout`
are the opposite — genuinely end-user-facing, need full CRUD with the scope-based
authorization described above.

## 4. Request flow — running a report end to end

1. Frontend fetches `GET /reports/{report_key}` once — returns the resolved
   `report_definition` + `report_column[]` + `report_criteria[]` for the requesting tenant.
2. Frontend fetches the effective default criteria/layout (the User → Tenant → System
   fallback described above).
3. User fills the criteria panel; frontend submits raw values. Backend validates each
   against `report_criteria` (`is_required`, `data_type`), then builds `@CriteriaJson`
   following the scalar/array/object-by-`control_type` convention above.
4. Execution engine resolves `proc_name`, opens a connection, **sets tenant session context**,
   and calls the proc with the criteria payload and `@MaxRows` as bound parameters.
5. Reads back the one result set as rows; returns them alongside the column metadata from
   step 1.
6. Grid renders using `report_column` metadata to configure sort/group/filter/aggregate
   behavior. No report-specific frontend code exists anywhere in this path.

## 5. Two rules that must never be violated

**Always call procs parameterized — never build the `EXEC` statement as a concatenated
string.** `proc_name` and `lookup_proc` come from admin-curated metadata (safe to place
directly in command text *because* they're validated against the catalog before use, not
because identifiers are inherently safe). Every criteria **value** came from the end user
this request and must always travel as a bound parameter — the JSON payload as one
`NVARCHAR` parameter is what makes this tractable for a framework where the number and type
of criteria varies per report.

**Tenant session context must be set at the start of every request, never assumed to
persist.** Business-table row-level security (on the actual data tables the report procs
query, not on `rpt` itself) depends on `sp_set_session_context`, and pooled connections are
reused across different tenants' requests — this has to live in a FastAPI dependency that
runs first in the request lifecycle, reusing whatever pattern DeevoAgent already has for this
rather than a new one.

## 6. Frontend — one generic page, not one page per report

A single report route takes a `report_key`, fetches metadata once, and renders two generic
components: a criteria panel switching on `control_type` to pick the input widget, and a
grid (ag-Grid or similar) configured entirely from `report_column`. Saved-view selectors are
dropdowns against the generic saved-criteria/saved-layout endpoints. Adding a report should
never require a new frontend file.

## 7. Current state

Database schema is complete and reviewed (two passes — see git history / prior review notes
if questions come up about *why* a column exists or doesn't). Next steps, in order, chosen so
the "actually generic" claim gets tested early rather than after a lot of code exists:

1. Catalog read services + one real report proc, hand-seeded via SQL
2. Execution engine — proves the dynamic-proc-call pattern end to end for that one report
3. Saved-criteria/saved-layout CRUD + the scope fallback resolution
4. React generic grid + criteria panel, wired to 1–3
5. A second and third report proc — **no backend or frontend code changes**, just new
   metadata + new procs. If this step requires touching application code, something leaked
   out of the metadata layer and should be caught here, not later.
