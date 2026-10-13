# Prompt — Transaction screens frontend (React) for the generic writer (`mtf/txn`)

This is the **frontend contract** for the generic transaction-screen renderer. The backend is split:

- **Metadata** lives in `deevo_mt_framework_backend` (`mtf/txn`): `GET /screens/{screen_key}`.
- **Lookups and record CRUD** are **product** APIs. Their URLs come from metadata (`lookup.api_base_path`, `screen.api_base_path`), not from hard-coded Lead paths.

The renderer is app-neutral. Any product that mounts `mtf.txn` and implements the envelope + lookup search contract can reuse it.

**How to use it.** Copy this file into the frontend repo, then adapt the copy to that repo's
conventions (UI kit, HTTP client, folder layout, routing, test tooling) — §0 lists everything that
is app-specific. Keep the API facts (§3–§9) unchanged; they describe the backends as built.

Lead is the **first proof screen** (DeevoFlow). §12 lists Lead-only facts for wiring the first
route. Do **not** create `LeadForm.tsx` or `if (screenKey === "lead")`.

---

## 0. Adapt before use

| Placeholder | Meaning | Example (DeevoFlow React) |
|---|---|---|
| `{ORIGIN}` | Host only | `http://localhost:8010` |
| `{API_BASE}` | Origin + prefix where **`mtf.txn` (and usually `mtf.rpt`)** is mounted | `http://localhost:8010/api/v1` |
| HTTP client | Authenticated client (Bearer + refresh) | shared Axios instance |
| `{FEATURE_DIR}` | Feature folder | `src/features/txn/` |
| Routes | One generic screen route | `/txn/:screenKey` (add) and `/txn/:screenKey/:id` (view/edit) |
| `tenantId` | Auth-store tenant — **query keys only, never sent** | `authStore.tenantId` |
| UI kit | App components | shadcn/ui + TanStack Query + Zod + React Hook Form |

**Do not join `{API_BASE}` onto `api_base_path`.** Both `screen.api_base_path` and
`lookup.api_base_path` are **host-relative** and already include the product prefix
(e.g. `/api/v1/crm/lead-screen`, `/api/v1/lookups/tenant-users`). Call them as
`{ORIGIN}{api_base_path}` (Axios `baseURL = {ORIGIN}` + that path, or an absolute URL).
`GET {API_BASE}/screens/{screen_key}` is the only call that uses `{API_BASE}`.

If the app already has a hand-built Lead (or Account) form, **do not** grow it. Add this generic
feature beside it. The old CRM Leads page may keep using `/crm/leads` until this screen is
accepted; then remove the old page.

---

## 1. Product rules (never violate)

1. **Generic, metadata-driven.** One `TransactionScreen` serves every `screen_key`. Adding a screen
   in SQL + a product envelope API must not need a new React form or `if (screenKey === …)`.
2. Branch only on metadata: `control_type`, `data_type`, `edit_mode`, `lookup`, `layout_type`,
   `permissions`. Never on field names like `owner_id` except when mapping lookup item keys
   (`return_field_key` / `display_field_key`).
3. **Never send `tenant_id` or `user_id`.** The JWT supplies both.
4. **View mode makes every field readonly**, regardless of `edit_mode`.
5. **Do not invent columns or endpoints.** If metadata omits a field, do not render it. If the
   envelope still contains that key, keep it in memory but do not show or PATCH it unless the user
   cannot see it (tenant-hidden — §4.1).
6. **No report→screen navigation in V1 of this UI.** Do not call `/reports/…/actions/…`. Open the
   screen from an app button or the existing entity list.

---

## 2. How the pieces fit

```mermaid
sequenceDiagram
    participant UI as TransactionScreen
    participant Meta as {API_BASE}/screens
    participant Rec as {ORIGIN}{api_base_path}
    participant Lu as {ORIGIN}{lookup.api_base_path}

    UI->>Meta: GET /{screenKey}
    alt mode = add
        Note over UI: defaults from metadata; no record GET
    else mode = view or edit
        UI->>Rec: GET /{id}
        UI->>Lu: GET ?ids=…   (labels for dropdown values)
    end
    Note over UI: merge metadata + record; apply mode + permissions
    Note over UI: user opens a dropdown
    UI->>Lu: GET ?search=&page=&page_size=
    alt Save add
        UI->>Rec: POST { record }
    else Save edit
        UI->>Rec: PATCH /{id} { record: changed, row_version }
    end
```

| Term | Meaning |
|---|---|
| **Screen** | One `screen_key` (e.g. `lead`). System-level metadata; tenant only overrides presentation. |
| **Section** | Group of fields: stacked (`layout_type=standard`) or tabs (`tabs`). |
| **Field** | One API property (`field_key`) + control + `edit_mode`. |
| **Lookup** | Reusable search API. Item keys are source-generic (`id`, `name`, `label`). |
| **Envelope** | `{ record, row_version, permissions }` from GET/POST/PATCH. |
| **Record permissions** | May be stricter than screen permissions (e.g. converted Lead cannot edit). |

---

## 3. Calling conventions

**Who can call:** JWT with a tenant. Missing tenant → `403 AUTH_FORBIDDEN`. `system` users without
a tenant cannot load screens.

**Auth:** every call uses the app's Bearer client.

**Repeated `ids`.** Axios default sends `ids[]=a`. The backend expects `ids=a&ids=b`. With Axios
≥ 1.x set `paramsSerializer: { indexes: null }` on lookup calls. With `fetch`, `append` each id.

**DELETE has a JSON body** `{ "row_version": "<base64>" }`. Axios: `axios.delete(url, { data: { row_version } })`.
A body-less DELETE is `422`.

**`row_version`** is an opaque base64 string. Store it; send it back unchanged. Do not decode it.

**Error helpers** (same idea as the reports UI): `txnErrorMessage`, `txnErrorCode`,
`txnErrorFields`. Support both shapes:

```json
{ "detail": { "code": "CRM_LEAD_INVALID", "message": "…", "fields": { "first_name": "…" } } }
```

```json
{ "detail": [ { "loc": ["body", "record", "first_name"], "msg": "…", "type": "…" } ] }
```

Map FastAPI `loc` ending in a `field_key` into the same per-field map.

---

## 4. APIs

### 4.1 `GET {API_BASE}/screens/{screen_key}` — metadata (MTF)

Encode `screen_key` with `encodeURIComponent`.

```ts
type ScreenMetadata = {
  screen_key: string
  display_name: string
  layout_type: "standard" | "tabs"
  api_base_path: string          // host-relative, e.g. "/api/v1/crm/lead-screen"
  permissions: {
    can_view: boolean
    can_add: boolean
    can_edit: boolean
    can_delete: boolean
  }
  sections: ScreenSection[]
}

type ScreenSection = {
  section_key: string
  display_name: string
  display_order: number
  column_count: number           // 1..4
  is_collapsible: boolean
  is_collapsed_default: boolean
  fields: ScreenField[]
}

type ScreenField = {
  field_key: string
  display_name: string
  data_type: "string" | "integer" | "decimal" | "date" | "datetime" | "boolean"
  control_type:
    | "text" | "textarea" | "number" | "date" | "datetime"
    | "dropdown" | "checkbox" | "email" | "phone"
  display_order: number
  column_span: number            // 1..4, cap at section.column_count
  is_required: boolean
  edit_mode: "editable" | "create_only" | "readonly"
  default_value: string | null   // literal; no @today
  max_length: number | null
  min_value: number | null
  max_value: number | null
  format_type: "decimal" | "currency" | "percent" | "weight" | null
  help_text: string | null
  lookup: ScreenLookup | null    // only when control_type === "dropdown"
}

type ScreenLookup = {
  lookup_key: string
  api_base_path: string          // host-relative
  return_field_key: string       // key on each lookup item (e.g. "id")
  display_field_key: string | null
  min_search_chars: number
  page_size: number
  columns: {
    field_key: string
    display_name: string
    display_order: number
    is_displayed: boolean
    is_searchable: boolean
    width: number | null
    format_type: string | null
  }[]
}
```

**403 `SCREEN_FORBIDDEN`** only when **all** screen operations are false. An add-only user still
gets metadata (`can_add: true`, others false).

**Tenant-hidden fields** are **omitted from `sections`** but **still present on `record`**. Do not
strip unknown `record` keys on GET. Do not send them on PATCH unless you treat them as dirty
(you should not — they are not on the form).

Do not display internal database ids from metadata (they are not returned).

### 4.2 Lookups — `GET {ORIGIN}{lookup.api_base_path}`

Two modes (do not mix):

| Mode | Query | Result |
|---|---|---|
| Search | `search`, `page` (1-based), `page_size` | Active rows; `has_more` if more exist |
| Resolve | `ids` repeated | Labels for stored values; **ignores** search/paging; max 500; includes **inactive** (not deleted) |

```json
{ "items": [ { "id": "01J…", "name": "Ada Lovelace", "email": "ada@example.com" } ], "has_more": false }
```

- Clamp `page_size` to `lookup.page_size`.
- Do not search until `search.length >= min_search_chars` (0 means search immediately, including
  empty search for the first page).
- **Value written to the record:** `item[lookup.return_field_key]` → `record[field.field_key]`.
- **Label shown:** `item[lookup.display_field_key]` (if `display_field_key` is null, use the
  return value as the label).
- Popup table: columns with `is_displayed`; search box filters via the API (`is_searchable` is
  server-side). Do not invent extra item keys.
- If the lookup call fails: field shows “Options unavailable”; do not block the rest of the form.

### 4.3 Record — `{ORIGIN}{screen.api_base_path}`

| Method | Path | Body | Success |
|---|---|---|---|
| GET | `/{id}` | — | 200 envelope |
| POST | `""` (collection) | `{ "record": { … } }` | 201 envelope |
| PATCH | `/{id}` | `{ "record": { …changed }, "row_version": "…" }` | 200 envelope |
| DELETE | `/{id}` | `{ "row_version": "…" }` | 204 |

```ts
type RecordEnvelope = {
  record: Record<string, unknown>   // includes id + every screen field_key
  row_version: string               // base64
  permissions: {
    can_view: boolean
    can_edit: boolean
    can_delete: boolean
  }
}
```

PATCH: **only changed keys**. Omitted = no change. `null` = clear. `null` on a required field → 422.

POST: send visible writable fields (editable + create_only). Omit readonly. Apply `default_value`
on the client for add mode so required dropdowns (e.g. status `new`) are present.

After POST 201, navigate to view (or edit) of `record.id` and keep the new `row_version`.

---

## 5. Modes, permissions, `edit_mode`

Route query: `?mode=add|view|edit`. Default: `add` when there is no `:id`, else `view`.

| Mode | Load record? | Save | Fields |
|---|---|---|---|
| **add** | No | POST if `screen.permissions.can_add` | `editable` and `create_only` enabled; `readonly` disabled |
| **view** | GET | none | all disabled; show Edit if `record.permissions.can_edit`, Delete if `can_delete` |
| **edit** | GET | PATCH if `record.permissions.can_edit` | `editable` enabled; `create_only` and `readonly` disabled |

Effective “can show this mode”:

- add: `screen.permissions.can_add` — else 403 page / hide the Add button.
- view: `screen.permissions.can_view` and GET succeeded.
- edit: `screen.permissions.can_edit` **and** `envelope.permissions.can_edit`.
- delete: `screen.permissions.can_delete` **and** `envelope.permissions.can_delete`.

If the user is in `?mode=edit` but record permissions say not editable (converted Lead), stay in
**view** and toast that the record is read-only.

`create_only` is writable **only on add**. On edit it looks like readonly.

---

## 6. Rendering

- Sort sections by `display_order`, fields by `display_order`.
- **standard:** stack sections. If `is_collapsible`, a disclosure; start collapsed when
  `is_collapsed_default`.
- **tabs:** one tab per section (same section list).
- CSS grid: `column_count` columns; field occupies `min(column_span, column_count)`.
- Label = `display_name`; required asterisk if `is_required`; `help_text` as hint.
- **Never** render `row_version`.

### Controls

| `control_type` | Widget | Value in `record` |
|---|---|---|
| `text`, `email`, `phone` | input | string or `null` if empty on PATCH |
| `textarea` | textarea | string or `null` |
| `number` | numeric input | integer or decimal per `data_type`; honor `min_value` / `max_value` |
| `date` | date picker | `"YYYY-MM-DD"` or `null` |
| `datetime` | datetime picker | ISO `YYYY-MM-DDTHH:mm:ss` (no offset; UTC) or `null` |
| `checkbox` | checkbox | JSON `true` / `false` (not a tri-state; unchecked = `false`) |
| `dropdown` | searchable picker + optional popup columns | `return_field_key` value or `null` |

`format_type` is **display only** (`currency`, `percent` = already 0–100, `decimal`, `weight`).
`max_length` is a client max. Tokens like `@today` are **not** supported; unparseable
`default_value` → empty.

Parse `default_value` (always a string or null) by `data_type` for add-mode initials:
`"true"`/`"false"` → bool; numbers; dates as `YYYY-MM-DD`.

Client-side: disable Save when a visible required field is empty. Still show server `fields`
errors — the server is authoritative (NOT NULL columns may be required even if `is_required` is 0).

---

## 7. Lookups (dropdown behaviour)

On view/edit, after GET record:

1. Collect each dropdown’s current `record[field_key]` if non-null.
2. `GET {lookup.api_base_path}?ids=v1&ids=v2` **per lookup_key** (group fields that share a lookup).
3. Cache `value → label` so the closed control shows the name, not the raw id.

On search: debounce; respect `min_search_chars`; request `page=1` first; if `has_more`, allow
“load more” with `page+1`. Do not prefetch the world.

Clearing a non-required dropdown: set the form value to `null` (PATCH will send `null` if dirty).

---

## 8. Save, dirty tracking, concurrency

Keep `baseline = envelope.record` and `row_version` after every successful GET/POST/PATCH.

**PATCH body `record`** = keys whose current value `!==` baseline (use a stable compare: dates as
strings, numbers as numbers, `null` vs `""` — treat empty string as `null` before compare).

**POST body `record`** = all visible writable fields you have values for (including defaults and
`false` checkboxes). Skip readonly. Skip empty optional strings (omit or `null` — server accepts
omit on POST for optional keys).

**409 `*CONFLICT`** (Lead: `CRM_LEAD_CONFLICT`): toast “Someone else saved this record”; **GET
again**; replace baseline and `row_version`; keep the user’s dirty values highlighted so they can
re-save. Do not silently overwrite the form without saying so.

**204 DELETE:** go back to the list (or catalog). Confirm first.

Do not send `id`, `tenant_id`, `is_converted`, or audit columns as writable keys (they may appear
as **readonly** fields — display only).

---

## 9. Errors → UI

Product codes vary by entity (`CRM_LEAD_*`). Handle by **suffix / family**, not by hard-coding
only Lead:

| Status / code pattern | UI |
|---|---|
| `422` + `detail.fields` (`*_INVALID`) | Inline under those `field_key`s; scroll to first |
| `422` + `detail` array | Map `loc` → field; else toast `msg` |
| `409` `*_CONFLICT` | Stale `row_version` — §8 reload |
| `403` `SCREEN_FORBIDDEN` | “You don’t have permission for this screen.” |
| `403` `*_FORBIDDEN` (record, e.g. converted) | Stay/switch to view; toast the `message` |
| `404` `*_NOT_FOUND` (record) | Not-found page (missing / deleted / other tenant) |
| `404` `SCREEN_NOT_FOUND` | Unknown `screen_key` |
| `404` lookup / `*_TENANT_USER_NOT_FOUND` on save | Inline on that dropdown if you can; else toast |
| `401` | Existing auth refresh / login |

---

## 10. Routes and chrome (adapt names)

Suggested (change to match the app router):

| Route | Mode |
|---|---|
| `/txn/:screenKey` | add (`?mode=add` implied) |
| `/txn/:screenKey/:id` | view by default; `?mode=edit` |

DeevoFlow first vertical: `/txn/lead` and `/txn/lead/:id`. Title = `metadata.display_name`.

Buttons:

- Add page: Save (POST), Cancel → previous list.
- View: Edit (if allowed), Delete (if allowed, confirm), Back.
- Edit: Save (PATCH), Cancel → discard dirty → view.

Do **not** replace the existing CRM Leads **list** in V1. Add “New lead” / row “Open” links that
navigate to these routes. List can keep `GET /api/v1/crm/leads`.

---

## 11. Not in this UI (V1)

- Report actions / drilldown
- Multiselect
- Header/detail child grids
- Tenant-config editor or permission-assignment admin
- Sending `tenant_id`
- Hard-coded Lead field layouts
- Using `/crm/lookups?category=` (management API) for screen dropdowns

---

## 12. First proof — Lead (DeevoFlow) — wiring only

Use these **only** to register the first route and list buttons. The renderer stays generic.

| Fact | Value |
|---|---|
| `screen_key` | `lead` |
| Metadata | `GET {API_BASE}/screens/lead` |
| `api_base_path` | `/api/v1/crm/lead-screen` |
| Lookups | `/lookups/tenant-users` (`id`,`name`,`email`); `/lookups/crm/{lead_source,industry,lead_group}` (`id`,`label`); `/lookups/lead-statuses` (`id`,`label`) |
| Converted | GET ok; `permissions.can_edit`/`can_delete` false; PATCH/DELETE → `403 CRM_LEAD_FORBIDDEN` |
| Old API | `/api/v1/crm/leads` list + old form **untouched** |

`return_field_key` is `id` on all current Lead lookups. `owner_id` in the record stores
**`tenant_user.id`**, not `app_user.id`. Status `id` is the status string (`new`, …).

---

## 13. Suggested frontend build order

Implement one step per request; inspect the frontend repo first.

1. Types + HTTP wrappers (`getScreen`, `getRecord`, `createRecord`, `patchRecord`, `deleteRecord`,
   `searchLookup`, `resolveLookupIds`) + error helpers. No UI.
2. `TransactionScreen` shell: load metadata; add mode with defaults; section layout; text controls;
   Save POST. No lookups.
3. View/edit: GET envelope, dirty PATCH, `row_version`, 409 reload.
4. Dropdowns: ids resolve + search + `paramsSerializer`.
5. Remaining controls (checkbox, date, number formats), permissions, Delete, converted read-only.
6. Wire Lead list “New” / row open. Manual test against `http://localhost:8010`.

---

## 14. First user message (frontend repo)

```text
Copy and follow TRANSACTION_FRONTEND_PROMPT.md (generic txn React contract).
Adapt §0 to this repo. Do not hard-code Lead fields.

Step 1 only: types + authenticated HTTP wrappers for
GET /screens/{key}, lookup search/ids, and the record envelope
(GET/POST/PATCH/DELETE). No UI yet. Show me the files you will add, then implement.
```
