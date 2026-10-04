# Generic Reporting Framework — Project Context

Read this before writing or editing any code in this project. It explains what the framework
is, why the database is shaped the way it is, and the rules that keep "generic" actually
generic as new reports get added. The SQL in this folder ([rpt_schema_v5.sql](rpt_schema_v5.sql))
is the source of truth for exact DDL — this document explains the *why* behind it and the
architecture that sits on top of it. The endpoint-by-endpoint API spec (rules, error codes,
request/response shapes, build order) is [prompts/rpt/REPORT_API_PROMPT.md](../prompts/rpt/REPORT_API_PROMPT.md).

## 1. What this is

A metadata-driven reporting framework for Deevolight's multi-tenant SaaS platform. The core
idea: **all report-specific business logic lives inside a single SQL Server stored procedure
per report.** Everything else — the filter panel, column layout, grouping, totals, saved
views — is generic and driven entirely by metadata tables. Adding a new report should mean
writing one new stored procedure plus a handful of new metadata rows, and **touching zero
backend or frontend application code.**

This is the `mtf.rpt` module inside `deevo_mt_framework_backend` (single shared database,
multiple tenants), reusing the same `auth`, `tenant`, and `audit` schemas, database standards,
and backend conventions in [CONVENTIONS.md](CONVENTIONS.md) — not a standalone product with
its own auth/tenant model.

## 2. The `rpt` schema — four tables

All DDL is in [rpt_schema_v5.sql](rpt_schema_v5.sql). Summary of what each table is for and
the non-obvious design decisions behind it:

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

**`report_key` resolution rule**: the unique indexes allow a tenant report and a system report
to share a `report_key`. When that happens, the tenant-owned report wins for that tenant;
every other tenant still gets the system report. This lookup lives in exactly one place
(`ReportCatalogService._resolve_report`) and is reused by the execution engine and the
saved-view services, so key resolution and tenant isolation are never re-implemented.

**Known V1 limitation — no audience column**: there is no per-report audience flag, so tenant
staff (`user_scope = 'tenant'`) and account portal users (`user_scope = 'tenant_account'`) see
the same report list. Revisit this (e.g. an `audience` column) before portal reports go live.

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
initial grid column width in px; a saved view's layout can override it.

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
options) takes the standard parameters `@SearchText`, `@Values`, `@MaxRows` and must return
exactly two columns named `value` and `label` — never per-proc column names. This is what
keeps the front-end dropdown component fully generic. Full signature in the API spec.

**`default_value` convention**: literal values (`'Open'`, `'US'`) store as-is. Reserve
`@today`, `@month_start`, `@year_start`, `@current_user`, `@current_tenant` as dynamic
expressions resolved by the application layer at render time — not implemented yet, but the
column needs no schema change to support it later.

### `report_saved_view` — saved views
One named saved view bundles **criteria and layout together** (filter-panel values plus
column order/visibility/width/sort/group/aggregates) — one save action, one named item in
the list, the way QuickBooks/Excel/Tableau-style "save this view" works. An earlier version
split these into `report_saved_criteria` + `report_saved_layout`; that flexibility wasn't
worth the fragile pairing between two unlinked tables for small/medium clients, so they
were merged.

Each view has **System / Tenant / User** scoping:

- `scope_type = 'system'`: `tenant_id` and `user_id` both `NULL` — platform-wide default,
  authored by SQL script in V1 (not editable through the API)
- `scope_type = 'tenant'`: `tenant_id` set, `user_id` `NULL` — visible to every user in that
  tenant; managed by tenant staff with the `owner` or `admin` role
- `scope_type = 'user'`: both set — visible only to that one user, who manages it

Enforced by `CK_report_saved_view_scope`. Filtered unique indexes guarantee unique
`view_name` per tier and at most one active `is_default = 1` row per tier per report. When
resolving the *effective* default for a user opening a report, fall back
User → Tenant → System (most specific wins) → base metadata defaults. For a tenant-owned
report the System tier never applies.

`criteria_json` and `layout_json` must be JSON objects with a top-level positive int
`"version"` (e.g. `{"version": 1, "columns": [...], "sort": [...], "group": [...]}`) so the
application can migrate older rows if the shape changes; an empty criteria set is stored as
`{"version": 1}`. Both are enforced by `CK_report_saved_view_*` constraints. The server adds
`version`; clients never send it.

`CK_report_saved_view_default_state` is a backstop: a default view can never be inactive or
deleted. The service must clear `is_default` in the **same write** that deactivates or
soft-deletes a view. Deleting a default never auto-promotes another view.

**Unenforced-by-design rule, must live in the service layer with a test**: if the parent
report's `scope_type = 'tenant'`, a saved view can't be `scope_type = 'system'`, and its
`tenant_id` must equal that report's own `tenant_id` — a tenant should never be able to save
a view against another tenant's custom report. For a `'system'` report, any scope is
allowed. This isn't a `CHECK` constraint because expressing it would require a cross-table
scalar UDF, which hurts write performance — it's an explicit application-layer validation.

## 3. Backend architecture — two data-access strategies, not one

The backend has two fundamentally different problems and should not try to solve them with
one tool:

**Catalog services** — CRUD/read access to the four `rpt` tables above. Known, fixed shape.
Use **SQLAlchemy 2.0** models with Pydantic v2 schemas, same as the rest of this repo, so ULID
generation, soft-delete filtering, `row_version` optimistic-concurrency checks, and
audit-log-on-mutation follow the existing patterns in [LAYERING.md](LAYERING.md) rather than
being reinvented. Catalog responses never expose `proc_name` or `lookup_proc`; criteria expose
`has_lookup` instead so database object names stay internal.

**Execution engine** — calls an *arbitrary* stored procedure by name and gets back an
*unknown-until-runtime* result shape. An ORM actively gets in the way here. Use a thin,
parameterized `pyodbc` wrapper: resolve `proc_name` from `report_definition`, call it with
bound parameters, read back whatever columns come out, return rows as plain dicts alongside
the already-known `report_column` metadata from the catalog (no need to re-derive column
shape from the query result).

Stack otherwise matches the rest of this repo: **FastAPI**, Pydantic v2, SQL Server via
`pyodbc`, ULID `varchar(26)` PKs, soft deletes, JWT auth with scope-based authorization
(`system`/`tenant`/`tenant_account` levels), layered `api/` → `services/` → models structure.
Report routes accept `tenant` and `tenant_account` scopes; `tenant_id` always comes from the
JWT. Errors use this repo's standard `{"detail": {"code", "message"}}` shape (plus a `fields`
map on validation errors), with `REPORT_*` codes listed in the API spec.

### Catalog authoring for V1: developer-authored, not an admin UI

`report_definition`/`report_column`/`report_criteria` are tightly coupled to a specific
proc's actual contract — `column_name` must match the proc's output, `criteria_key` must
match what the proc's `OPENJSON` expects. Treat a report and its metadata as one deployable
unit for V1: **author new reports via SQL script/migration alongside the proc itself**, not
through a runtime admin CRUD API. The backend only needs *read* endpoints for these three
tables (to serve metadata to the frontend). `report_saved_view` is the opposite —
genuinely end-user-facing, needs full CRUD with the scope-based authorization described
above (except System views, which are SQL-authored in V1).

## 4. Request flow — running a report end to end

1. Frontend fetches `GET /api/reports/{report_key}` once — returns the resolved
   `report_definition` + `report_column[]` + `report_criteria[]` for the requesting tenant.
2. Frontend fetches the effective default view, `GET /api/reports/{report_key}/views/default`
   (the User → Tenant → System fallback described above), and dropdown options from
   `GET /api/reports/{report_key}/lookups/{criteria_key}`.
3. User fills the criteria panel; frontend submits raw values to
   `POST /api/reports/{report_key}/run`. Backend validates each against `report_criteria`
   (shape, `data_type`, `is_required`), then builds `@CriteriaJson` following the
   scalar/array/object-by-`control_type` convention above.
4. Execution engine resolves `proc_name`, takes one connection, **sets tenant session context
   on that same connection**, and calls the proc with the criteria payload and `@MaxRows` as
   bound parameters.
5. Reads back the one result set, checks its columns exactly match `report_column`, and
   returns the rows (the frontend already has the column metadata from step 1).
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
reused across different tenants' requests. A FastAPI dependency takes one raw connection,
sets `tenant_id` and `user_id` with `sp_set_session_context` on **that** connection, runs
every proc call for the request on it, and clears both keys in a `finally` block before the
connection returns to the pool (never `@read_only = 1`, which can't be cleared). Report and
lookup procs read the tenant via `SESSION_CONTEXT(N'tenant_id')`; it is never a client
parameter.

## 6. Frontend — one generic page, not one page per report

A single report route takes a `report_key`, fetches metadata once, and renders two generic
components: a criteria panel switching on `control_type` to pick the input widget, and a
grid (ag-Grid or similar) configured entirely from `report_column`. The saved-view selector
is a dropdown against the generic `/views` endpoints. Adding a report should never require a
new frontend file.

## 7. Current state

Database schema v5 is complete, reviewed, and applied (see git history for *why* a column
exists or doesn't). Steps, in order, chosen so the "actually generic" claim gets tested early
rather than after a lot of code exists:

1. **Done** — catalog read services + five hand-seeded sample reports
   ([rpt_seed_sample_report.sql](rpt_seed_sample_report.sql); `GET /api/reports`,
   `GET /api/reports/{report_key}`)
2. **Done** — execution engine: `GET /api/reports/{report_key}/lookups/{criteria_key}` and
   `POST /api/reports/{report_key}/run`, proving the dynamic-proc-call pattern end to end
3. Saved-view CRUD + the User → Tenant → System default resolution
4. React generic grid + criteria panel, wired to 1–3
5. More report procs — **no backend or frontend code changes**, just new metadata + new
   procs. If this step requires touching application code, something leaked out of the
   metadata layer and should be caught here, not later.

The detailed build order for steps 2–3 is in [prompts/rpt/REPORT_API_PROMPT.md](../prompts/rpt/REPORT_API_PROMPT.md).
