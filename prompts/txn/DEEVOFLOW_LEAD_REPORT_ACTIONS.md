# Prompt — DeevoFlow Lead list report → Lead screen (product seed)

Paste this whole file into a **Cursor chat whose workspace is `deevoflow_backend`**. Do not
implement this from `deevo_mt_framework_backend`.

The generic report→screen engine already exists in the sibling framework (`mtf/rpt`). This
product only **seeds** `rpt.report_action` / `rpt.report_action_param` on the existing Lead
list report, and makes sure that report’s result set includes the Lead id. Do **not** copy
action-resolution logic into `app/`. Do **not** add Lead-specific Python.

Governing contracts (read-only, sibling repo):

- `../deevo_mt_framework_backend/prompts/rpt/REPORT_API_PROMPT.md` §§2 and 2b (actions + resolve)
- `../deevo_mt_framework_backend/docs/txn_schema_v2.sql` (`rpt.report_action`, `rpt.report_action_param`)
- Lead screen already specified in [DEEVOFLOW_LEAD_SCREEN.md](DEEVOFLOW_LEAD_SCREEN.md)
- React reports UI and `TransactionScreen` are **separate frontend workspaces** — not this prompt

This repo’s rules win on layering, commits, error codes, and URL prefix
(`docs/CONVENTIONS.md` in `deevoflow_backend`).

---

## Product decisions — these win

1. **Seed only.** No new FastAPI routes. No changes to `/api/v1/crm/lead-screen` or
   `/api/v1/crm/leads`. No changes to `mtf` source (editable checkout is fine to *call*).
2. **Reuse the existing Lead list report.** Find it in `sql/rpt_deevoflow_reports.sql` (or
   wherever CRM reports are seeded). Do **not** create a second list report. If there is
   truly no Lead list report, stop and say so — creating a report is a different prompt
   (`NEW_REPORT_PROMPT.md`).
3. **`screen_mode` is only `add` | `view`.** The CHECK on `rpt.report_action` forbids `edit`.
   Converted leads are view-only; that is decided by `GET /crm/lead-screen/{id}`
   (`permissions.can_edit = false`), not by the report.
4. **Resolve `target_key` for view is `id`.** The generic screen route is
   `/txn/:screenKey/:id`. Map the report’s Lead-id column → `id`.
5. **Optional Edit button** (if product wants it on the grid): seed a second *row* action
   with `action_key` such as `edit_lead`, still `screen_mode = 'view'`, same param map.
   The reports React app (later) opens `?mode=edit` after the same resolve. Do not invent
   `screen_mode = 'edit'`.
6. **No report→report drilldown** in this work.

---

## What the framework already does (do not rebuild)

Mounted in DeevoFlow today as `/api/v1/reports` (same `mtf.rpt` router). After a framework
version that includes report actions is installed (`uv sync` against the sibling checkout):

| Call | Already implemented in MTF |
|---|---|
| `GET /api/v1/reports/{report_key}` | Catalog now includes `actions[]` (live `rpt.report_action` + params). Screen actions are **omitted** unless the JWT user may use that mode on the target screen (`add` → `can_add`, `view` → `can_view`). Internal ids are never returned. |
| `POST /api/v1/reports/{report_key}/actions/{action_key}/resolve` | Maps **only** declared `report_action_param` rows. Extra keys in `row` / `criteria` are ignored. |

**Resolve request**

```json
{ "row": { "<id_column>": "01J…" }, "criteria": {} }
```

Toolbar Add may send `{}`.

**Resolve response (screen)**

```json
{ "target_type": "screen", "screen_key": "lead", "mode": "view",
  "params": { "id": "01J…" } }
```

Add returns `"mode": "add"` and `"params": {}`.

| Error | When |
|---|---|
| `404 REPORT_NOT_FOUND` | Source report not visible |
| `404 REPORT_ACTION_NOT_FOUND` | Unknown/inactive action, or target screen missing |
| `403 SCREEN_FORBIDDEN` | User cannot add/view the Lead screen |
| `422 REPORT_ACTION_INVALID` | Declared `source_key` missing/empty (`detail.fields`) |

The Lead **screen** contract is already product-owned and should already be live:

- Metadata: `GET /api/v1/screens/lead`
- Envelope: `/api/v1/crm/lead-screen` (`screen_key` = `lead`)
- Screen row id (from `sql/txn_lead_screen.sql`): look up `txn.screen.id` where
  `screen_key = 'lead'` — do not guess. The seed script suggested
  `01JTXNDVFSC000000000000001`.

---

## What DeevoFlow must do

### A. Lead id must be a `report_column` on the list report

Resolve cannot invent the id. The list stored procedure **must return** the Lead primary
key, and `rpt.report_column.column_name` must match that result column **exactly**.

- Prefer `column_name = id` (same as `crm.lead.id` / envelope `record.id`).
- If the proc already aliases it (`lead_id`, …), keep that name and use it as
  `report_action_param.source_key`. Do not rename a live column unless nothing depends on it.
- The column may be `is_displayable = 0` (hidden on the grid). It still must be in `/run`
  rows so the frontend can send it as `row.<source_key>`.

If the proc does not select the id today: `CREATE OR ALTER` the proc **and** insert/update
the `rpt.report_column` row in the same seed script. Column names on `/run` must still
match active `report_column` rows (V1 contract).

### B. Seed two actions (plus optional extras)

`action_type = 'screen'`. `target_screen_id` = the live `txn.screen.id` for `lead`.
`target_report_id` and `screen_mode` follow the CHECK (screen ⇒ report id NULL, mode
`add` or `view`).

| action_key | display_name | display_location | screen_mode | params | display_order |
|---|---|---|---|---|---|
| `add_lead` | Add Lead | `toolbar` | `add` | none | 10 |
| `view_lead` | View Lead | `row` | `view` | `source_type=column`, `source_key=<id column>`, `target_key=id` | 20 |

Optional:

| action_key | display_location | notes |
|---|---|---|
| `view_lead` (second row) or a distinct key | `column` | Same param map. Set `trigger_column_key` to a **displayed** column (`company`, `first_name`, …). CHECK: column actions require `trigger_column_key`; toolbar/row require it NULL. |
| `edit_lead` | `row` | Same as view (`screen_mode='view'`, same param). React later appends `?mode=edit`. |

Do **not** hard-code CRM field layouts, Lead routes, or `if report_key == …` in Python.

### C. File / ids

Add or extend a SQL script next to the existing report seed, e.g.
`sql/rpt_deevoflow_lead_actions.sql` (or a clearly marked section in
`sql/rpt_deevoflow_reports.sql`). Run as `deevo_ddl`. Re-runnable: delete **this script’s**
rows by id prefix, then insert. **Do not** delete other reports’ actions.

Suggested id prefix (26 chars, Crockford): `01JRPTDVFA` + table code + number.

```
01JRPTDVFAAC00000000000001   -- report_action add_lead
01JRPTDVFAAC00000000000002   -- report_action view_lead
01JRPTDVFAAP00000000000001   -- report_action_param view_lead → id
```

Resolve `report_id` from the live definition (do not invent it):

```sql
DECLARE @ReportId varchar(26);
DECLARE @ScreenId varchar(26);
DECLARE @IdColumn varchar(100);  -- e.g. 'id' — must match report_column.column_name

SELECT @ReportId = id
FROM rpt.report_definition
WHERE report_key = @LeadListKey   -- fill from Step 0
  AND is_deleted = 0 AND is_active = 1;

SELECT @ScreenId = id
FROM txn.screen
WHERE screen_key = 'lead'
  AND is_deleted = 0 AND is_active = 1;

-- Fail the script if either is NULL.
```

`UNIQUE (report_id, action_key)` where `is_deleted = 0` — re-runs must delete or reuse the
same `action_key`s.

---

## What the frontend will do later (not this repo)

Reports React: render `actions[]` (toolbar / row / column), `POST …/resolve` with the
clicked row, navigate to `/txn/lead` (add) or `/txn/lead/{id}` (view). Transaction React
already owns the screen. Do **not** implement React here.

---

## Master instructions

Inspect this codebase first. Reuse the existing report seed style (`sql/rpt_deevoflow_reports.sql`,
`sql/txn_lead_screen.sql`).

Do **not**:

- Modify `mtf/` or add routes in DeevoFlow for resolve/catalog.
- Change Lead envelope APIs or the old `/crm/leads` list.
- Implement `screen_mode = 'edit'`.
- Seed report→report actions.
- Write a Lead-specific form or `if (report_key == "…")`.

Implement **only** the step named in the user message. After each step: files changed,
how you verified, assumptions, pending.

---

## Build order (one step per user message)

### Step 0 — Assessment only (no code)

Map:

1. How `mtf.rpt` is mounted (`/api/v1/reports`).
2. The Lead list `report_key`, `rpt.report_definition.id`, proc name, and
   `rpt.report_column` list — does an id column exist? Is it in the proc SELECT?
3. `txn.screen.id` for `screen_key = 'lead'`.
4. Framework version / editable path: does the running app have
   `POST /api/v1/reports/{report_key}/actions/{action_key}/resolve` in OpenAPI?
   If not, `uv sync` against a framework checkout that includes report actions
   (sibling `deevo_mt_framework_backend`).

End with a file-by-file plan for **Step 1 only**. Do not implement it yet.

### Step 1 — Id column on the Lead list report (only if missing)

If Step 0 found the id already in proc + `report_column`, skip this step and say so.

Otherwise: add the column to the proc and a matching `rpt.report_column` row. Hidden
(`is_displayable = 0`) is fine. Existing `/run` tests must still pass (column set must
match metadata).

### Step 2 — Seed `add_lead` + `view_lead`

SQL only (plus a tiny integration test if the repo already tests seeded reports). Apply as
`deevo_ddl`.

Verify with a tenant JWT against `http://localhost:8010`:

```http
GET /api/v1/reports/{lead_list_key}
```

`actions[]` includes `add_lead` (toolbar, `screen_key=lead`, `screen_mode=add`) and
`view_lead` (row, `screen_mode=view`, param `source_key` → `target_key=id`). No
internal ids in the JSON.

```http
POST /api/v1/reports/{lead_list_key}/actions/add_lead/resolve
{ }
```

→ `{ "target_type": "screen", "screen_key": "lead", "mode": "add", "params": {} }`

```http
POST /api/v1/reports/{lead_list_key}/actions/view_lead/resolve
{ "row": { "<id_column>": "<a real lead id>" }, "criteria": {} }
```

→ `{ "target_type": "screen", "screen_key": "lead", "mode": "view", "params": { "id": "<same id>" } }`

Also confirm: missing `row` id → `422 REPORT_ACTION_INVALID`; unknown `action_key` →
`404 REPORT_ACTION_NOT_FOUND`.

### Step 3 (optional) — Column click and/or `edit_lead`

Only if product wants them. Same resolve contract. `edit_lead` stays `screen_mode='view'`.

---

## Security checklist (mandatory)

- Do not put `tenant_id` in action params or accept it from the client.
- `target_screen_id` / `report_id` are server metadata only; the API returns `screen_key` /
  `report_key`.
- A user without Lead `can_add` must not see `add_lead` on GET; resolve of that action is
  `403 SCREEN_FORBIDDEN` (MTF). Do not bypass this in product code.
- The id in `row` is whatever the **report row** already showed; resolve does not re-check
  that the Lead exists (the screen GET does, tenant-scoped, 404).

---

## First user message to start (Step 0)

```text
Read prompts/txn/DEEVOFLOW_LEAD_REPORT_ACTIONS.md (copy this file into the
deevoflow_backend repo if it is not there yet).

Workspace is deevoflow_backend. Do not modify mtf source.

Step 0 only: inspect this codebase. No code changes.

Find the Lead list report (report_key, proc, columns), the txn.screen id for
screen_key=lead, and whether GET /api/v1/reports/{key} already returns actions[]
and the resolve route exists in OpenAPI.

End with a file-by-file plan for Step 1 (id column if missing) or Step 2
(seed actions) if the id column is already present. Do not implement yet.
```

Then: “go on Step 1” or “go on Step 2”, one at a time.
