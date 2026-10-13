# Prompt — DeevoFlow Lead transaction screen (product work)

Paste this whole file into a **Cursor chat whose workspace is `deevoflow_backend`**. Do not implement this from `deevo_mt_framework_backend`.

The generic transaction framework (`mtf/txn`) already exists in the sibling repo. This product owns: mounting that router, seeding the Lead screen, lookup **search** APIs, and adapting Lead CRUD to the screen envelope. Do **not** copy screen-metadata or permission-resolution logic into `app/`.

Governing design (read-only, sibling repo):

- `../deevo_mt_framework_backend/prompts/txn/Deevolight_Generic_Transaction_Screens_V2_Architecture.pdf`
- `../deevo_mt_framework_backend/prompts/txn/Deevolight_Generic_Transaction_Screens_Backend_API_Design_FINAL.pdf`
- `../deevo_mt_framework_backend/docs/txn_schema_v2.sql`
- Live APIs already in MTF: `GET /api/screens/{screen_key}`, `require_screen_permission(screen_key, operation)`
- React contract (separate frontend workspace): [TRANSACTION_FRONTEND_PROMPT.md](TRANSACTION_FRONTEND_PROMPT.md)

This repo’s rules win on layering, commits, error codes, and URL prefix (`docs/CONVENTIONS.md` in `deevoflow_backend`).

---

## Product decisions (2026-10-12) — these win over anything else in this file

1. **New endpoints, old ones untouched.** The envelope lives at **`/api/v1/crm/lead-screen`** (POST) and **`/api/v1/crm/lead-screen/{id}`** (GET/PATCH/DELETE) in a new module `app/crm/api/lead_screen.py`. Do **not** change `app/crm/api/lead.py`, `LeadCreate`/`LeadUpdate`/`LeadRead`, or the behavior of `/api/v1/crm/leads[/{id}]` — the current React Leads page keeps using them until the new screen is accepted; then the old API and page are removed. `LeadService` may gain new methods; existing methods keep their behavior.
2. **Readonly enforcement comes from metadata at runtime.** On POST/PATCH, load `edit_mode` for screen `lead` from `txn.screen_field` (live rows) and reject `readonly` keys (POST and PATCH) and `create_only` keys (PATCH). Changing a field’s mode in SQL must take effect without a code change. Use `mtf.txn.models` read-only; do not reimplement permission resolution.
3. **Tenant-hidden fields are display-only.** `screen_field_config.is_displayed = 0` does not change the API: the field is still returned in `record` and still writable.
4. **No audit logging** for Lead screen writes in this work. Commit the same way `LeadService` does today.
5. **Lookups are named by data source, reusable across screens** (not per screen): `/api/v1/lookups/tenant-users`, `/api/v1/lookups/crm/{category}`, `/api/v1/lookups/lead-statuses`. Items use **generic keys** (`id`, `name`/`label`, …). Each `txn.lookup` row maps them: `return_field_key` = the item key holding the value (e.g. `id`), `display_field_key` = the item key holding the label. The screen field’s own `field_key` (e.g. `owner_id`) is where the picked value goes in `record`.
6. **Converted leads** on the new endpoints: GET works with `can_edit`/`can_delete` false; PATCH and DELETE return **403 `CRM_LEAD_FORBIDDEN`**.
7. **PATCH semantics** on the new endpoint: omitted key = no change; explicit `null` = clear the field; `null` on a required field = 422.

**Deployment prerequisite.** `mtf.txn` is on the framework’s `feature/txn` branch. The Azure deploy vendors the framework from `main`, so before deevoflow ships with the `txn` router mounted: merge `feature/txn` → `main`, bump the framework version (date scheme, e.g. `2026.10.12`), run `uv lock` here, and apply `docs/txn_schema_v2.sql` to Azure SQL. Otherwise Azure fails at startup with `No module named 'mtf.txn'`.

---

## Master instructions

Inspect this codebase first. Reuse FastAPI, SQLAlchemy, JWT (`require_scope("tenant")`, `get_tenant_id`), `like_pattern`, `require_lookup` / `require_tenant_user`, and existing `LeadService`.

Do **not**:

- Redesign or break Generic Report Writer V1 (`mtf.rpt` mount).
- Implement a generic dynamic-SQL CRUD engine.
- Put Lead / CRM field lists or Lead routes into `mtf/`.
- Replace `GET /api/v1/crm/lookups?category=` (lookup **management**). Txn lookups are a **separate** search contract.
- Implement report actions, report `permission_mode` wiring, or React.

Implement **only** the step named in the user message. After each step: files changed, APIs, tests, assumptions, pending.

Keep today’s error codes: `CRM_LEAD_NOT_FOUND`, `CRM_LEAD_CONFLICT`, `SCREEN_FORBIDDEN`, `AUTH_FORBIDDEN`. New on the screen endpoints only: `CRM_LEAD_FORBIDDEN` (403, converted lead). Add `reason: "stale_version"` on concurrency 409 only if it does not break existing clients.

---

## What is already true (do not assume the PDF’s sample Lead)

| Item | Actual DeevoFlow |
|---|---|
| App | `http://localhost:8010`, prefix **`/api/v1`** |
| MTF mounts today | `/api/v1/auth`, `/api/v1/tenant`, `/api/v1/reports` — **`mtf.txn` is not mounted yet** |
| Lead routes | `app/crm/api/lead.py` → **`/api/v1/crm/leads`** (existing; **unchanged** by this work) |
| Lead screen routes | **new** `app/crm/api/lead_screen.py` → **`/api/v1/crm/lead-screen`** |
| Lead model | `crm.lead` — `first_name` / `last_name` (there is **no** `lead_name`) |
| Owner FK | `owner_id` → **`auth.tenant_user.id`**, not `app_user.id` |
| Category lookups | `lead_source_id`, `industry_id`, `group_id` → `crm.lookup` (`lead_source`, `industry`, `lead_group`) |
| Status | varchar + `LeadStatus` literal: `new`, `contacted`, `in_progress`, `qualified`, `unqualified`, `lost` |
| Converted | `is_converted`; update currently 404s converted rows |
| List | `GET /api/v1/crm/leads` paginated `LeadRead` — **keep this** for the existing CRM UI |
| GET/POST/PATCH/DELETE (old) | return/accept `LeadRead` / `LeadCreate` / `LeadUpdate`; DELETE is 204 with **no** `row_version` — **keep as is** |
| Services | **commit in the service** (unlike MTF). No audit logging for Lead in this work (decision 4). |
| Framework dep | `deevo-mt-framework-backend` path `../deevo_mt_framework_backend` editable |

`field_key` in `txn.screen_field` **must** equal the JSON property on the Lead envelope (`first_name`, `owner_id`, …), not a SQL alias.

---

## Target contract the generic React screen will call

After this work, a tenant JWT can:

1. `GET /api/v1/screens/lead` — MTF metadata (no DeevoFlow logic).
2. `GET /api/v1/lookups/tenant-users?search=&page=&page_size=` and `?ids=` (plus `/lookups/crm/{category}`, `/lookups/lead-statuses`) — product lookups, reusable across screens.
3. `POST /api/v1/crm/lead-screen` and `GET/PATCH/DELETE /api/v1/crm/lead-screen/{id}` — product CRUD in the **record envelope**, gated by `require_screen_permission("lead", …)`. The old `/api/v1/crm/leads` API is untouched.

### Envelope (GET / POST / PATCH)

```json
{
  "record": {
    "id": "01J...",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "owner_id": "01J...",
    "status": "new"
  },
  "row_version": "AAAAAAAAB9E=",
  "permissions": {
    "can_view": true,
    "can_edit": true,
    "can_delete": false
  }
}
```

- `record` contains **screen field_keys plus `id`**. Do **not** put `tenant_id`, `is_deleted`, `deleted_by`, or other server-owned columns in `record`.
- `row_version` stays opaque bytes (existing base64 JSON).
- `permissions` are **record-level**: start from screen effective flags, then force `can_edit`/`can_delete` false when `is_converted` is true (view still allowed).
- POST body: `{ "record": { ... } }` (no `row_version`).
- PATCH body: `{ "record": { ... }, "row_version": "..." }`. Omitted keys = no change (`exclude_unset=True`). Explicit `null` = clear the field; `null` on a required field = 422.
- DELETE: require `row_version` (JSON body `{ "row_version": "..." }` is fine). Soft-delete as today. 404 if missing/other tenant; 409 `CRM_LEAD_CONFLICT` if stale; 403 `CRM_LEAD_FORBIDDEN` if converted.
- `record` always includes every screen field_key, including fields a tenant has hidden (decision 3).

All of this applies to **`/api/v1/crm/lead-screen` only**. The old `/api/v1/crm/leads` list, GET, POST, PATCH, and DELETE keep their current shapes and behavior, and their existing tests must keep passing unchanged.

### Txn lookup search (new; do not reuse `/crm/lookups?category=`)

```
GET {api_base_path}?search=abc&page=1&page_size=50
GET {api_base_path}?ids=01J...&ids=01J...
```

```json
{
  "items": [ { "id": "01J...", "name": "Ada Lovelace", "email": "ada@example.com" } ],
  "has_more": false
}
```

Item keys are **generic to the data source** (`id`, `name`, `label`, `email`, …), never screen field names like `owner_id`. The `txn.lookup` row says which item key is the value (`return_field_key`) and which is the label (`display_field_key`); `txn.lookup_column.field_key` values must be item keys. The generic screen writes `item[return_field_key]` into `record[screen_field.field_key]`.

Rules: tenant + `is_deleted = 0`; parameterized LIKE and escape `%`, `_`, `[` (extend `like_pattern` if `[` is missing); clamp `page_size` to the `txn.lookup.page_size` (max 500); `min_search_chars`; `ORDER BY` deterministic; fetch `page_size + 1` for `has_more`; `ids` uses the same security filters; `require_scope("tenant")`.

---

## Screen seed (system screen, `permission_mode = open`)

File: `sql/txn_lead_screen.sql` (same idea as `sql/rpt_deevoflow_reports.sql`). Run as `deevo_ddl`. Re-runnable: delete this script’s rows by id prefix `01JTXNDVF`, then insert. **Do not** use delete-and-reinsert in production once users have `screen_field_config` / `screen_permission` rows.

Suggested ids (26-char ULID-shaped, prefix `01JTXNDVF`):

| Table | Example id |
|---|---|
| `txn.screen` | `01JTXNDVFSC000000000000001` |
| `txn.lookup` | `01JTXNDVFLK000000000000001` … |
| `txn.screen_section` | `01JTXNDVFSE000000000000001` … |
| `txn.screen_field` | `01JTXNDVFFL000000000000001` … |

```
screen_key        = lead
display_name      = Lead
api_base_path     = /api/v1/crm/lead-screen
layout_type       = standard
permission_mode   = open
allow_view/add/edit = 1
allow_delete      = 1   (CRM already deletes; set 0 if you want the screen to hide Delete)
```

### Lookups to seed (`txn.lookup` + `txn.lookup_column`)

Set **both** `return_field_key` and `display_field_key`. Columns’ `field_key` values must appear in the search JSON.

| lookup_key | api_base_path | return / display | Item keys | Source |
|---|---|---|---|---|
| `tenant_user` | `/api/v1/lookups/tenant-users` | `id` / `name` | `id`, `name`, `email` | `auth.tenant_user` + `auth.app_user`; `id` = **`tenant_user.id`** (what `owner_id` stores); `name` = first + last, else email |
| `crm_lead_source` | `/api/v1/lookups/crm/lead_source` | `id` / `label` | `id`, `label` | `crm.lookup` `category='lead_source'` |
| `crm_industry` | `/api/v1/lookups/crm/industry` | `id` / `label` | `id`, `label` | `crm.lookup` `category='industry'` |
| `crm_lead_group` | `/api/v1/lookups/crm/lead_group` | `id` / `label` | `id`, `label` | `crm.lookup` `category='lead_group'` |
| `lead_status` | `/api/v1/lookups/lead-statuses` | `id` / `label` | `id`, `label` | Fixed `LeadStatus` list (not `crm.lookup`); `id` is the status value (`new`, …) |

`/api/v1/lookups/crm/{category}` accepts only an allow-list of categories (start with `lead_source`, `industry`, `lead_group`; add `account_group`, `opportunity_group`, … when those screens arrive). Unknown category → 404. These lookups are named for reuse: the Account screen later points its owner/industry fields at the same rows.

Popup columns: at least the display key (`is_searchable=1`). The `tenant_user` popup may add `email`.

### Sections and fields

Use `data_type` / `control_type` from MTF CHECKs: string/integer/decimal/date/datetime/boolean and text/textarea/number/date/datetime/dropdown/checkbox/email/phone.

**Section `general` (order 10, 2 columns)**

| field_key | control | required | edit_mode | notes |
|---|---|---|---|---|
| first_name | text | 1 | editable | max_length 100 |
| last_name | text | 1 | editable | max_length 100 |
| salutation | text | 0 | editable | max_length 10 |
| company | text | 0 | editable | |
| title | text | 0 | editable | |
| owner_id | dropdown → `tenant_user` | 0 | editable | |
| status | dropdown → `lead_status` | 1 | editable | default_value `new` (`crm.lead.status` is NOT NULL; the default keeps it hideable per tenant) |
| is_hot | checkbox | 0 | editable | boolean |

**Section `contact` (order 20)** — `email` (email), `phone`/`mobile` (phone), `website` (text).

**Section `address` (order 30)** — `address1`, `address2`, `city`, `state`, `zip`, `country`.

**Section `details` (order 40)** — `lead_source_id` → `crm_lead_source`, `industry_id` → `crm_industry`, `group_id` → `crm_lead_group` dropdowns; `revenue` number/decimal format currency; `employees` number/integer; `confidence` number/integer min 0 max 100; `description` textarea; `email_opt_out` checkbox.

**Section `system` (order 90)** — `id`, `created_at`, `updated_at`, `is_converted` all **readonly**. Include `id` so view mode can show it. `is_converted` is boolean/checkbox readonly.

Do not put `tenant_id`, `row_version`, `is_deleted`, or converted-to-account ids on the screen unless product asks later.

`dropdown` rows **must** have `lookup_id`. Non-dropdown must have `lookup_id` NULL.

“Required” on PATCH (explicit `null` → 422) means `is_required = 1` in `txn.screen_field` **or** a NOT NULL `crm.lead` column (`first_name`, `last_name`, `status`, `is_hot`, `email_opt_out`). POST leaves required-ness to `LeadCreate`; an omitted `status` defaults to `new`.

---

## Build order (one step per user message)

### Step 0 — Assessment only (no code)

Map Lead routes, schemas, tests, existing `/crm/lookups`, how MTF routers are mounted. List conflicts with this prompt (the product decisions at the top are settled — don’t reopen them). End with a file-by-file plan for **Step 1 only**.

### Step 1 — Mount MTF screen metadata

- `main.py`: `from mtf.txn.api import router as mtf_txn_router` then `app.include_router(mtf_txn_router, prefix="/api/v1")` (same pattern as `mtf_rpt_router`).
- `uv sync` so the editable framework includes `mtf.txn`.
- Test: OpenAPI has `/api/v1/screens/{screen_key}`; unauthenticated GET is 401/403. Do not seed yet (will 404 until Step 2).

### Step 2 — Seed `txn.*` for Lead

- Add `sql/txn_lead_screen.sql` and apply as `deevo_ddl`.
- Verify `GET /api/v1/screens/lead` with a tenant JWT returns sections/fields and `permissions` for an open screen with no permission row (`allow_*` defaults).
- No Python except maybe a tiny integration test.

### Step 3 — Lookup search APIs

Implement the three data-source routes from the lookups table (one module is fine, e.g. `app/crm/api/txn_lookups.py` mounted at `/api/v1/lookups`). **First PR-quality slice:** `tenant-users` (search + ids + tenant + paging). Then `crm/{category}` with its allow-list, then static `lead-statuses`. Item keys are generic (`id`, `name`, `label`, `email`), not screen field names.

Reuse `like_pattern`; clamp page size; do not call these from LeadService as a substitute for `require_tenant_user` / `require_lookup` on write.

### Step 4 — Lead screen GET envelope

- New module `app/crm/api/lead_screen.py`, router prefix `/lead-screen` under the CRM router → `/api/v1/crm/lead-screen`. Leave `app/crm/api/lead.py` untouched.
- `GET /{id}`: `require_screen_permission("lead", "view")` **and** `require_scope("tenant")`.
- Return envelope; `record` = every screen field_key + `id` (hidden fields included). Record-level: converted ⇒ `can_edit`/`can_delete` false.
- Other tenant / missing / deleted ⇒ `404 CRM_LEAD_NOT_FOUND` (not 403).
- Existing Lead tests must pass unchanged; add new tests for the screen endpoint.

### Step 5 — Lead screen POST envelope

- `POST ""`: `require_screen_permission("lead", "add")`.
- Validate with Pydantic `extra="forbid"`; no `tenant_id` / audit columns in input.
- Keep `_validate_refs`.
- Reject `readonly` field_keys, read at runtime from `txn.screen_field` (decision 2) → 422 listing the offending keys.
- Commit as `LeadService` does today (no audit — decision 4).
- Return the created envelope (201).

### Step 6 — Lead screen PATCH envelope

- `PATCH /{id}`: `require_screen_permission("lead", "edit")`.
- `exclude_unset=True`; explicit `null` clears; `null` on a required field → 422.
- Reject `readonly` and `create_only` keys from runtime metadata → 422.
- Converted lead → **403 `CRM_LEAD_FORBIDDEN`**.
- `row_version` mismatch → 409 `CRM_LEAD_CONFLICT`.
- Add a new `LeadService` method for this; do not change the existing `update()` behavior used by the old route.

### Step 7 — Lead screen DELETE

- `DELETE /{id}`: `require_screen_permission("lead", "delete")`.
- Require `row_version` (JSON body); 404 missing/other tenant, 409 stale, **403 `CRM_LEAD_FORBIDDEN`** converted.
- Soft delete as today (`is_deleted`, `deleted_at`/`deleted_by`). No audit.

### Later (not this prompt)

- Report → Lead navigation (`rpt.report_action`).
- React generic `TransactionScreen`.
- Other entities (Account, …): new seed + entity envelope in **this** repo; reuse the data-source lookups; no MTF change if metadata API is enough.
- Remove the old `/api/v1/crm/leads/{id}` GET/POST/PATCH/DELETE and the old React Leads page once the new screen is accepted.
- Audit logging for screen writes.

---

## Imports the product will use (do not reimplement)

```python
from mtf.txn.api.deps import require_screen_permission
from mtf.txn.api import router as mtf_txn_router  # main.py only
```

```python
Depends(require_screen_permission("lead", "view"))   # GET
Depends(require_screen_permission("lead", "add"))    # POST
Depends(require_screen_permission("lead", "edit"))   # PATCH
Depends(require_screen_permission("lead", "delete")) # DELETE
```

Screen key `"lead"` is a **DeevoFlow constant**, not something MTF knows.

---

## Security checklist (mandatory)

- Tenant only from JWT (`get_tenant_id` / `CurrentUser.tenant_id`).
- Every Lead query includes `tenant_id` and `is_deleted = 0`.
- POST/PATCH: `owner_id` via `require_tenant_user`; lookup FKs via `require_lookup(..., category=...)`.
- Mass assignment: `extra="forbid"`; never accept `tenant_id`, `is_converted`, `is_deleted`, audit columns on write; reject `readonly` / `create_only` keys per runtime metadata.
- Lookups: every query filters by tenant from the JWT; `ids=` uses the same filters as search.
- FastAPI is the security boundary; React permissions are UX only.

---

## First user message to start (Step 0)

```text
Read prompts/txn/DEEVOFLOW_LEAD_SCREEN.md in this repo, including the
"Product decisions (2026-10-12)" section, which is settled.

Workspace is deevoflow_backend. Do not modify mtf source.

Step 0 only: inspect this codebase. No code changes.

Map Lead CRUD, CRM lookups, MTF router mounts, and tests. Confirm the
new /api/v1/crm/lead-screen endpoints won't touch the existing
/api/v1/crm/leads API or the React Leads page.

List any remaining conflicts. End with a file-by-file plan for Step 1
(mount mtf.txn) only. Do not implement Step 1 yet.
```

Then: “go on Step 1”, “go on Step 2”, … one at a time.
