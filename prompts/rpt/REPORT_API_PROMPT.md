# Backend prompt: Generic Reporting Framework API

Build the FastAPI endpoints below in the `mtf.rpt` module of `deevo_mt_framework_backend`,
on top of the `rpt` schema in [docs/rpt_schema_v5.sql](../../docs/rpt_schema_v5.sql)
(`report_definition`, `report_column`, `report_criteria`, `report_saved_view`).
Design background and the *why* behind the schema:
[docs/REPORTING_FRAMEWORK_CONTEXT.md](../../docs/REPORTING_FRAMEWORK_CONTEXT.md).
Frontend contract for these endpoints (copied into each consuming app):
[REPORT_FRONTEND_PROMPT.md](REPORT_FRONTEND_PROMPT.md).
Adding a report (procs + metadata rows, no code): [NEW_REPORT_PROMPT.md](NEW_REPORT_PROMPT.md).

Follow this repo's conventions ([docs/CONVENTIONS.md](../../docs/CONVENTIONS.md),
[docs/LAYERING.md](../../docs/LAYERING.md)): FastAPI, Pydantic v2, SQLAlchemy 2.0 (sync) +
`pyodbc` on SQL Server, ULID `varchar(26)` IDs generated in services, soft deletes,
`row_version` optimistic concurrency, JWT auth, `api/` → `services/` → models layering.

**Paths.** Routes below are relative to where the `rpt` router is mounted:
`/api/reports/...` in this repo, `/api/v1/reports/...` in `deevoflow_backend`
(which mounts `mtf.rpt.api.router` under `/api/v1`).

Two data-access strategies, not one:
- **Catalog endpoints** (`/reports`, `/reports/{report_key}`, `/views*`) — known, fixed
  row shape. Use SQLAlchemy models and `ReportCatalogService`, like the rest of `mtf`.
- **Execution endpoints** (`/run`, `/lookups/{criteria_key}`) — call an *arbitrary*
  stored proc by name and get back an *unknown-until-runtime* result shape. Use a thin,
  parameterized `pyodbc` wrapper, not the ORM.

Build the shared execution infrastructure once (see Build order) — every rule below
is meant to live in one place, not be re-implemented per endpoint.

---

## Cross-cutting rules — apply to every endpoint below

1. **Tenant context, same physical connection, every request.** All endpoints take
   only a tenant JWT (`user_scope` `tenant` or `tenant_account`); the frontend never
   sends `tenant_id`, and `user_scope = system` gets `403`. A FastAPI dependency
   resolves `tenant_id` and `user_id` from the JWT, acquires **one raw pyodbc
   connection** from the pool (`engine.raw_connection()`), calls
   `sp_set_session_context` for both keys **on that connection**, and every stored proc
   call for this request runs on that same connection before it's returned to the pool:
   ```
   Get connection A → sp_set_session_context on A → execute proc on A → return A to pool   ✓
   Set context using connection A → execute using connection B                              ✗ WRONG
   ```
   Setting context on one connection and executing on another silently returns another
   tenant's data — pass the same connection object through explicitly.
   In a `finally` block, clear both keys (set to `NULL`) right before the connection
   goes back to the pool. **Do not use `@read_only = 1`**: a read-only key can't be
   cleared, and the pooled connection would then fail the next request that sets it.
   Never send `tenant_id` inside `criteria_json` or as a client-supplied parameter.
   Every report/lookup proc reads it itself via `SESSION_CONTEXT(N'tenant_id')`.

2. **Always parameterized, never string-built.** `proc_name` and `lookup_proc` come
   from curated metadata — safe to place in command text only because they come from
   the catalog row resolved for this request, and must also match a strict
   `schema.name` identifier pattern (letters, digits, underscore) before being quoted as
   `[schema].[name]`. Every criteria value and every lookup `q`/`values` input is live
   user input and must always travel as a bound parameter.

3. **Row governor, clamped server-side.** A client-supplied `max_rows` (on `/run`) or
   `limit` (on a lookup) is a ceiling *request*, never a mandate:
   `effective_max_rows = max(1, min(client value, server cap))`. For `/run` the cap is
   `report_definition.default_max_rows` (also the value used when the client omits it);
   for lookups the cap is 200 and the default 50. Never pass the client's number through
   unclamped.

4. **Truncation, detected cheaply — report procs and lookup procs alike.** Every
   report proc's and lookup proc's final `SELECT` uses `TOP (@MaxRows + 1)`. After
   fetching, if `len(rows) > effective_max_rows`, trim the extra row and set
   `truncated` / `has_more` to `true`; otherwise `false`. No second `COUNT(*)` query.

5. **Query timeout.** Every proc call runs with a statement timeout from settings
   (`DEEVO_REPORT_QUERY_TIMEOUT_SECONDS`, default 60). A timeout is
   `REPORT_EXECUTION_FAILED`.

6. **Access control on every report.** Resolve the report only through
   `ReportCatalogService._resolve_report(tenant_id, report_key)` — visible reports are
   `scope_type = 'system'`, or `scope_type = 'tenant' AND tenant_id = caller's tenant`;
   a tenant report wins over a system report with the same key. Saved views add the
   schema's app-layer rule: a view under a `'tenant'`-scoped report can never be
   `scope_type = 'system'`, and its `tenant_id` must equal that report's `tenant_id`.
   Validate on every write.

7. **Criteria validation — one shared `validate_report_criteria()`.** Used by `/run`,
   `POST /views`, and `PATCH /views` so the rules can't drift:
   - **Shape**, from `control_type`: scalar (text/number/date/dropdown/bool), array
     (multiselect), `{"from","to"}` object (daterange).
   - **Scalar type**, from `data_type` — checked in addition to shape. `int` accepts
     integers and integer strings (`"42"`, since lookup values are always strings) and
     rejects `10.75`; `decimal` accepts numbers and numeric strings; `date` is
     `YYYY-MM-DD`; `datetime` is ISO 8601; `bool` is `true`/`false` only. A multiselect
     with `data_type=string` rejects `[100, 200]`. Values are normalized to their
     canonical JSON type before building `@CriteriaJson`.
   - **Null/empty normalization**, before the required check: `null`, `""`, `[]`, and
     `{"from": null, "to": null}` all count as *omitted*. Omitted criteria are left out
     of `@CriteriaJson` entirely. A required criterion that normalizes to omitted fails.
   - **Partial date ranges are valid**: `from` only → `>=`; `to` only → `<=`; both →
     range. Validate `from <= to` when both are supplied.
   - Reject unknown `criteria_key`s. On any failure raise `REPORT_CRITERIA_INVALID`
     with a `fields` map keyed by `criteria_key` — never build `@CriteriaJson` from
     invalid input.
   - `default_value` tokens (`@today`, …) are not resolved in V1.

8. **Layout validation — one shared `validate_report_layout()`.** Used by
   `POST /views` and `PATCH /views`. Layout shape (the client never sends `version`):
   ```json
   {
     "columns":    [ { "column_name": "name", "visible": true, "width": 240 } ],
     "sort":       [ { "column_name": "name", "direction": "asc" } ],
     "group":      [ "account_type" ],
     "aggregates": [ { "column_name": "amount", "type": "sum" } ]
   }
   ```
   Array order is display/sort/group order. `direction` is `asc`|`desc`; aggregate
   `type` is `sum`|`avg`|`count`|`min`|`max`; `width` is a positive int or `null`.
   - Every `column_name` must exist in this report's active `report_column` set; no
     duplicates within one array.
   - Capability flags: a visible column needs `is_displayable=1`, a sort column
     `is_sortable=1`, a group column `is_groupable=1`, an aggregate `is_aggregatable=1`.
     A hand-POSTed layout can never do more than the UI allows.
   - Failure raises `REPORT_LAYOUT_INVALID` with a `fields` map (e.g. `"sort[0]"`).

9. **Stored-proc output contract, checked once per execution, before row processing.**
   A report proc's result-set columns must **exactly** equal this report's active
   `report_column.column_name` set; a lookup proc's must be exactly `{value, label}`.
   Check `cursor.description` first. A mismatch, a missing proc, or any failure that
   isn't the caller's fault is `REPORT_EXECUTION_FAILED` (500), not a validation error —
   metadata/proc drift needs to surface loudly in logs, not quietly as a 4xx.

10. **Error shape — this repo's standard, everywhere.** Raise through
    `mtf.shared.exceptions` helpers so every error is:
    ```json
    { "detail": { "code": "REPORT_CRITERIA_INVALID", "message": "...", "fields": { "created_date": "..." } } }
    ```
    `fields` is present only on validation errors.

    | Code | Status | When |
    |---|---|---|
    | `REPORT_NOT_FOUND` | 404 | `report_key` not visible to the caller |
    | `REPORT_LOOKUP_NOT_FOUND` | 404 | criterion missing, not dropdown/multiselect, or no `lookup_proc` |
    | `REPORT_VIEW_NOT_FOUND` | 404 | view missing or not visible to the caller |
    | `REPORT_CRITERIA_INVALID` | 422 | `validate_report_criteria()` failure |
    | `REPORT_LAYOUT_INVALID` | 422 | `validate_report_layout()` failure |
    | `AUTH_FORBIDDEN` | 403 | wrong scope, or not allowed to manage that view tier |
    | `REPORT_VIEW_CONFLICT` | 409 | duplicate view name or default in a tier, or `row_version` mismatch |
    | `REPORT_EXECUTION_FAILED` | 500 | proc missing, output mismatch, timeout, DB error |

    Never let a raw SQL constraint violation (e.g. `UQ_report_saved_view_*`) reach the
    client — translate it with `mtf.shared.db_integrity`. For `REPORT_EXECUTION_FAILED`
    keep the message generic (`"The report could not be executed."`) and log the real
    exception — proc name, SQL text, stack trace — server-side only.

11. **Audit.** Saved-view create, update, and delete write `audit.audit_log` rows
    (`insert`/`update`/`delete`) like other `mtf` mutations. `/run` and lookups are not
    audited in V1.

---

## Stored procedure contract

Both proc families read tenant context from `SESSION_CONTEXT` themselves — it is never
a parameter the client or the API layer passes in.

**Report proc** (e.g. `rpt.usp_sales_by_region`):
```sql
CREATE OR ALTER PROCEDURE rpt.usp_sales_by_region
    @CriteriaJson nvarchar(max),
    @MaxRows      int
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TenantId varchar(26) = CONVERT(varchar(26), SESSION_CONTEXT(N'tenant_id'));
    IF @TenantId IS NULL
        THROW 50001, 'Tenant session context is not set.', 1;

    SELECT TOP (@MaxRows + 1)
        r.region        AS region,
        SUM(s.amount)   AS sales_amount
    FROM sales.fact_sales AS s
    JOIN sales.region     AS r ON r.id = s.region_id
    WHERE s.tenant_id = @TenantId
      -- ...criteria predicates parsed from @CriteriaJson via OPENJSON/JSON_VALUE;
      -- a criterion absent from the JSON means "no filter"...
    GROUP BY r.region;
END
```

**Lookup proc** (standard signature, e.g. `rpt.usp_lookup_salesperson`):
```sql
CREATE OR ALTER PROCEDURE rpt.usp_lookup_salesperson
    @SearchText nvarchar(200) = NULL,
    @Values     nvarchar(max) = NULL,   -- JSON array of value strings, e.g. ["C001","C002"]
    @MaxRows    int           = 50
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @TenantId varchar(26) = CONVERT(varchar(26), SESSION_CONTEXT(N'tenant_id'));

    SELECT TOP (@MaxRows + 1)
        CONVERT(varchar(50), p.id) AS value,   -- always a string, even if the key is numeric
        p.full_name                AS label
    FROM sales.salesperson AS p
    WHERE p.tenant_id = @TenantId
      AND (@SearchText IS NULL OR p.full_name LIKE '%' + @SearchText + '%')
      AND (@Values IS NULL OR CONVERT(varchar(50), p.id) IN (SELECT value FROM OPENJSON(@Values)))
    ORDER BY p.full_name;
END
```

Framework-level sample procs live in [docs/rpt_seed_sample_report.sql](../../docs/rpt_seed_sample_report.sql).
Product-specific report procs (e.g. DeevoFlow CRM reports) live in that product's repo.

---

## Endpoints

### 1. `GET /reports` — report catalog
**Status: built** (`mtf/rpt/api/report.py`).
All reports visible to the caller's tenant (system-wide + their own tenant-scoped reports),
ordered by `display_name`, `report_key`. **Not paginated** — no `skip`/`limit`, no cap; the
number of report definitions is small. Unknown query params are ignored.

### 2. `GET /reports/{report_key}` — report metadata
**Status: built.**
The resolved `report_definition` plus active `report_column[]`, `report_criteria[]`,
and `actions[]`, each ordered by `display_order`. Static metadata only — no saved-view
resolution (see #6). Never exposes `proc_name`/`lookup_proc`; criteria carry `has_lookup`
instead. Action rows never expose internal ids (`id`, `target_screen_id`, `target_report_id`).

`actions[]` comes from live `rpt.report_action` (+ live `report_action_param`). A **screen**
action is omitted unless the caller may use that `screen_mode` on the target
(`add` → `can_add`, `view` → `can_view` via `ScreenPermissionService`). A **report** action
is omitted unless the tenant can see a report with that `report_key`. Missing or inactive
targets are omitted; they do not 404 the catalog response.

```json
{
  "action_key": "open_sample",
  "display_name": "Open Sample",
  "action_type": "screen",
  "display_location": "row",
  "trigger_column_key": null,
  "display_order": 10,
  "screen_key": "sample_screen",
  "screen_mode": "view",
  "report_key": null,
  "params": [
    { "source_type": "column", "source_key": "record_id", "target_key": "id" }
  ]
}
```

### 2b. `POST /reports/{report_key}/actions/{action_key}/resolve` — navigation
**Status: built** (`ReportActionService`, `mtf/rpt/services/report_action.py`).
The client sends the current grid row and/or criteria. The server maps only declared
`report_action_param` rows and returns trusted navigation. Extra client keys are ignored.

```json
{ "row": { "record_id": "01J…" }, "criteria": {} }
```

Toolbar Add may send `{}`. `row` is required for any `source_type=column` param;
`criteria` for `source_type=criteria`. Missing/empty declared sources →
`422 REPORT_ACTION_INVALID` with `detail.fields` keyed by `source_key`.

Screen target (after `ScreenPermissionService` allows `add` / `view`):

```json
{ "target_type": "screen", "screen_key": "sample_screen", "mode": "view",
  "params": { "id": "01J…" } }
```

`mode` is only `add` | `view`. Edit is decided later by the screen envelope.

Report target (after the tenant can see that `report_key`); mapped values are
adapted to the target criterion shape, then validated with
`validate_report_criteria()` against the **visible** target report. A scalar copied
from a grouped row onto a **multiselect** criterion becomes a one-item list
(`"new"` → `["new"]`). Lists, daterange objects, and scalar targets are unchanged.
`/run` still requires a list for multiselect; this wrap is resolve-only.

```json
{ "target_type": "report", "report_key": "account_summary",
  "criteria": { "account_code": "A100" } }
```

Errors: `404 REPORT_NOT_FOUND` (source or invisible target report),
`404 REPORT_ACTION_NOT_FOUND` (unknown/inactive action or broken screen target),
`403 SCREEN_FORBIDDEN` (target screen mode not allowed),
`422 REPORT_CRITERIA_INVALID` (mapped report-target values fail the V1 contract).
Never exposes internal ids.

Frontend add-on (copy into the React repo):
[REPORT_FRONTEND_REPORT_DRILLDOWN_PROMPT.md](REPORT_FRONTEND_REPORT_DRILLDOWN_PROMPT.md).

### 3. `GET /reports/{report_key}/lookups/{criteria_key}` — lookup options
**Status: built** (`ReportLookupService`, `mtf/rpt/services/report_lookup.py`).
- Resolve the `report_criteria` row by `criteria_key` for this report.
  `REPORT_LOOKUP_NOT_FOUND` if it doesn't exist, its `control_type` isn't
  `dropdown`/`multiselect`, or `lookup_proc` is null.
- Query params: `q` (free-text search, optional, max 200 chars), `values` (**repeated**
  query param — `?values=C001&values=C002`; `values: list[str] | None = Query(None)`),
  `limit` (default 50, capped at 200 — rule 3). When `values` is sent without `limit`,
  the default grows to `len(values)` (still capped at 200) so every selected label resolves.
- Call `lookup_proc` with the standard signature: `q` → `@SearchText`, the `values`
  list → `@Values` (JSON-encoded array), clamped `limit` → `@MaxRows`.
- Output must be exactly `value`, `label` (rule 9). `value` is always serialized as a
  string; `validate_report_criteria()` converts it to the criterion's `data_type` on
  the way into `/run`.
- Truncation per rule 4:
  ```json
  { "items": [ { "value": "C001", "label": "ABC Jewelers" } ], "has_more": true }
  ```
- No `lookup_mode` metadata — every lookup is search-capable; the frontend renders a
  filterable combobox uniformly. `values` is how the frontend resolves labels for
  values already selected (e.g. loaded from a saved view).
- Runs with tenant session context (rule 1).

### 4. `POST /reports/{report_key}/run` — execute report
**Status: built** (`ReportRunService`, `mtf/rpt/services/report_run.py`).
Request:
```json
{ "criteria": { "account_type": ["customer","vendor"], "status": "active",
                "created_date": { "from": "2026-01-01", "to": "2026-12-31" } },
  "max_rows": 20000 }
```
- Validate `criteria` with `validate_report_criteria()` (rule 7).
- Clamp `max_rows` (rule 3). Call `proc_name` parameterized with `@CriteriaJson` (the
  validated, normalized criteria, JSON-encoded) and `@MaxRows`, on the session-context
  connection (rule 1), with the timeout (rule 5).
- Check the output contract (rule 9) before processing rows.
- Response:
  ```json
  { "report_key": "sales_by_region", "row_count": 1, "truncated": false,
    "rows": [ { "region": "West", "sales_amount": 18400.00 } ] }
  ```
  Row keys exactly match `report_column.column_name`. Value encoding: `decimal`/`int` →
  JSON number, `date` → `"YYYY-MM-DD"`, `datetime` → ISO 8601 (UTC, no offset), `bool` →
  `true`/`false`, `NULL` → `null`. Don't resend column metadata — the frontend has it
  from #2.
- Client-side only, no backend work: CSV/Excel/PDF export, grouping, sorting, in-grid
  filtering on loaded rows (`report_column.is_filterable`).

### Saved view response shape (used by #5–#8)
```json
{ "id": "01J...", "view_name": "Q3 Regional Review", "scope_type": "tenant",
  "is_default": false, "can_edit": true,
  "criteria": { "region": ["West","East"] },
  "layout": { "columns": [...], "sort": [...], "group": [...], "aggregates": [...] },
  "row_version": "AAAAAAAAB9E=", "updated_at": "2026-10-02T21:52:00" }
```
`criteria`/`layout` are returned without the stored `version` key. `can_edit` reflects
the role rules in #7 for the current caller.

### 5. `GET /reports/{report_key}/views` — list saved views
**Status: built** (`ReportSavedViewService`, `mtf/rpt/services/report_saved_view.py`).
Every active view visible to the caller for this report: `scope_type='system'` rows,
their tenant's `scope_type='tenant'` rows, and *only their own* `scope_type='user'` rows.
Includes `criteria`/`layout` so "load this view" needs no second call. Not paginated.

### 6. `GET /reports/{report_key}/views/default` — effective default
**Status: built.**
Resolves `User default → Tenant default → System default` in one place and returns the
first match, or `204 No Content` if none exists — the frontend then falls back to the
base defaults in #2 (`is_default_visible`, `default_value`, …). For a tenant-owned
report the `system` tier never applies (rule 6).

### 7. `POST /reports/{report_key}/views` — create a saved view
**Status: built** (`ReportSavedViewService.create_view`).
Request:
```json
{ "view_name": "Q3 Regional Review", "scope_type": "tenant",
  "criteria": { "region": ["West","East"] },
  "layout": { "columns": [...], "sort": [...], "group": [...], "aggregates": [...] },
  "is_default": false }
```
- Run `criteria` through `validate_report_criteria()` and `layout` through
  `validate_report_layout()` — the same validators `/run` uses — then store each as
  `{"version": 1, ...}`. An empty criteria object is stored as `{"version": 1}`.
- `tenant_id` comes from the JWT; `user_id` (for `user` scope) is the caller.
  Enforce rule 6.
- **Role rules (decided)**, behind an authorization hook
  `authorize(user, "report.view.manage_tenant")` so real RBAC can replace it later:
  - `user` scope — any `tenant` or `tenant_account` user, on their own views only.
  - `tenant` scope — tenant staff (`user_scope = tenant`) with `auth.tenant_user.role`
    `owner` or `admin`.
  - `system` scope — not creatable or editable through the API in V1 (`403`); system
    views are authored by SQL script, like report metadata.
- If `is_default: true`, clear the prior default in the same tier inside one
  transaction (clear → insert → commit). The filtered unique index stays the final
  authority under a race — translate its duplicate-key error to `REPORT_VIEW_CONFLICT`.
- Duplicate `view_name` in the same tier → `REPORT_VIEW_CONFLICT`.
- `201 Created` with the saved view.

### 8. `PATCH /reports/{report_key}/views/{view_id}` — update a saved view
**Status: built** (`ReportSavedViewService.update_view`).
Partial update of `view_name`, `criteria`, `layout`, `is_default`. **`row_version` is
required** (base64, as in other `mtf` PATCH bodies); a mismatch is
`REPORT_VIEW_CONFLICT`. `scope_type` is immutable and not a PATCH-able field — to move a
view to another tier, create a new one. Same validators and default-clearing
transaction as #7, same role rules. `REPORT_VIEW_NOT_FOUND` if the view isn't visible
to the caller (don't leak other tenants' or users' views). `200 OK` with the view.

### 9. `DELETE /reports/{report_key}/views/{view_id}` — delete a saved view
**Status: built** (`ReportSavedViewService.delete_view`).
Soft delete: set `is_deleted = 1`, `is_default = 0`, and `deleted_by` in the same write
— `CK_report_saved_view_default_state` rejects a deleted row still flagged default.
Do **not** auto-promote another view to default; the fallback chain in #6 resolves it
at read time. Same visibility and role rules as #8. `204 No Content`.

---

## Build order

Build the shared foundation once, then layer the endpoints on top:

1. ✅ **Proc contract**: update sample/product procs to the signatures above
   (`TOP (@MaxRows + 1)`, lookup `@SearchText`/`@Values`/`@MaxRows`). Done for the
   framework samples; DeevoFlow procs are updated in that repo.
2. ✅ **Shared errors**: `validation_error()` (422 + `fields`) and `internal_error()`
   (500, generic message, logged) in `mtf.shared.exceptions`.
3. ✅ **Execution infrastructure** (`mtf/rpt/execution/`): `open_report_connection()`
   + `get_report_connection` dependency in `mtf/rpt/api/deps.py` (rule 1),
   `quote_proc_name()` (rule 2), `clamp_max_rows()` (rule 3), `execute_proc()` with
   timeout (rule 5), truncation (rule 4), and output-contract check (rule 9).
4. ✅ **`validate_report_criteria()`** + `criteria_to_json()` (rule 7) in
   `mtf/rpt/services/criteria_validation.py`.
5. ✅ Lookups (#3) — nothing else works without dropdown/multiselect data.
6. ✅ Run (#4) — the core execution path.
7. ✅ **Saved view model + `validate_report_layout()`** (rule 8) — `ReportSavedView` in
   `mtf/rpt/models/report_saved_view.py`, validator in
   `mtf/rpt/services/layout_validation.py`.
8. ✅ Saved views, read side (#5, #6).
9. ✅ **Authorization hook** (role rules in #7) — `ReportViewAuthorizer` in
   `mtf/rpt/services/view_authorization.py`; built with #5 because `can_edit` needs it.
10. ✅ Saved views, write side (#7, #8, #9), with audit rows (rule 11) — audit rows are
    written in the same transaction as the view change; `row_version` is the ORM
    `version_id_col` on `ReportSavedView`, so every UPDATE is also conditional.
