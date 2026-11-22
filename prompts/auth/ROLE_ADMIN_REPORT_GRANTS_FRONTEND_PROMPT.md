# Prompt — Role Admin report grants (React) — CRM menu fix

Paste this whole file into a **Cursor chat whose workspace is `deevoflow_react`**.

This extends tenant Role Admin so admins can grant **report** access on custom roles.
Without it, CRM list menus (Leads, Accounts, Contacts, Opportunities, Tasks) stay hidden
even when `screen.*` permissions are ticked.

Do **not** implement this from `deevo_mt_framework_backend`. Do **not** change the RBAC
backend here. Do **not** implement this in `deevoflow_backend`.

Parent contract: [`ROLE_ADMIN_FRONTEND_PROMPT.md`](ROLE_ADMIN_FRONTEND_PROMPT.md). Keep its
rules (JWT tenant, gate on `api.auth.role.update`, templates read-only, grant by id).

---

## Why this exists (read before coding)

CRM sidebar items are wired as **reports**, not screens:

| Menu label | Nav type | Gate |
|---|---|---|
| Leads / Accounts / Contacts / Opportunities / Tasks | `item_type=report` | `role_report.can_view` on `crm_*_list` |
| Notes | `item_type=screen` | `screen.note.view` |
| Reference Data | `item_type=screen` | `menu.crm_lookups.view` |

**Add / Edit / View** buttons on a list report are separate: they navigate to `txn.screen`
and need **screen** grants (`screen.lead.create`, `screen.lead.view`, `screen.lead.update`, …).

So for a CRM member role you need **both**:

1. **Reports tab** — `can_view` (and optional `can_export`) on `crm_lead_list`,
   `crm_account_list`, `crm_contact_list`, `crm_opportunity_list`, `crm_task_list`
2. **Permissions grid** — `screen.{entity}.view|create|update|delete|export` (already built)

Ticking only the permission grid shows Notes (and WF menus if `menu.wf_*.view` is granted).
It does **not** show Leads/Accounts/….

Do **not** hide or invent nav items in React. After grants change, refetch nav
(`GET {API_BASE}/nav/modules` and module items) and `/auth/me`.

---

## 0. Adapt before use

Same placeholders as the parent Role Admin prompt (`{API_BASE}`, HTTP client, Roles page).

**Backend first.** OpenAPI / live API must expose:

- `GET {API_BASE}/tenant/reports` → grantable report catalog (Role Admin only)
- `GET|POST {API_BASE}/tenant/roles/{role_id}/reports`
- `PATCH|DELETE {API_BASE}/tenant/roles/{role_id}/reports/{report_id}`

If `GET /tenant/reports` is missing, stop and say the sibling framework checkout is behind.
Do **not** use `GET {API_BASE}/reports` for this screen — that list is filtered by the
caller’s own `can_view`, so a thin admin sees **zero** rows.

---

## 1. Product rules (never violate)

1. Same Role Admin gate: show only when `/auth/me` → `permissions` includes
   `api.auth.role.update`.
2. **Custom roles only.** Templates (`is_system`) stay read-only — no report grant edits.
3. Grant by **`report_id`** from `GET /tenant/reports`, never by inventing a `report_key` string
   in the POST body (you may **display** `report_key` / `display_name`).
4. Do not send `tenant_id` in query or body.
5. Do not call system default-report APIs (`/auth/roles/.../default-reports`).
6. Do not wrap routes under `/crm`. Call `/tenant/...` and `/nav/...` directly.
7. After saving report grants on a role that the signed-in user holds, invalidate nav + me
   queries so the sidebar updates.

---

## 2. APIs

All require tenant JWT + `api.auth.role.update`.

### Catalog (new)

`GET {API_BASE}/tenant/reports` → **200** array of:

```ts
{
  id: string           // 26-char ULID — use this in POST
  report_key: string   // e.g. "crm_lead_list"
  display_name: string
  description: string | null
  scope_type: "system" | "tenant"
}
```

Not filtered by the admin’s personal report access. Prefer sorting/grouping by `report_key`
prefix (`crm_`, `tenant_`, …) in the UI.

### Grants on a role

| Method | Path | Body / notes |
|---|---|---|
| GET | `/tenant/roles/{role_id}/reports` | Current grants |
| POST | `/tenant/roles/{role_id}/reports` | `{ "report_id", "can_view": true, "can_export": false }` → **201** |
| PATCH | `/tenant/roles/{role_id}/reports/{report_id}` | `{ "row_version", "can_view?", "can_export?", "is_active?" }` |
| DELETE | `/tenant/roles/{role_id}/reports/{report_id}` | **204** |

Grant row shape includes `report_id`, `can_view`, `can_export`, `row_version` (base64).
Join to the catalog by `report_id` → `report_key` / `display_name` for labels.

`can_export` requires `can_view` (backend enforces). Turning view off while export is on → error.

---

## 3. UI — Reports tab on a custom role

On **Settings → Roles**, when a **custom** role is selected, add a second tab (or section)
next to the permission grid:

**Permissions** | **Reports**

### Reports tab

- Load in parallel: `GET /tenant/reports` and `GET /tenant/roles/{role_id}/reports`.
- Table / checklist:
  - Columns: Report (`display_name` + muted `report_key`), **View**, **Export**
  - Checked View iff a live grant has `can_view`
  - Checked Export iff grant has `can_export` (disable Export when View is unchecked)
- Save = diff vs last fetch:
  - New view/export → `POST` with `{ report_id, can_view, can_export }`
  - Changed flags → `PATCH` with `row_version`
  - Cleared view → `DELETE` (or PATCH `can_view: false` if you prefer soft deactivate —
    prefer **DELETE** for a clean grant list)
- Templates: same list, all controls disabled; caption that platform templates are read-only.
- Highlight CRM list keys useful for DeevoFlow testing:
  `crm_lead_list`, `crm_account_list`, `crm_contact_list`, `crm_opportunity_list`,
  `crm_task_list` (optional filter chip “CRM lists”).

### Helper copy (one line under the tab)

“CRM list menus need View on these reports. Add/Edit buttons still use the Permissions
tab (`screen.*`).”

---

## 4. Verification checklist (lg / local)

As tenant **admin** (`api.auth.role.update`):

1. Open custom role `crm_member` (or create one).
2. Permissions tab: ensure Lead/Account/Contact/Opportunity/Task/Note screen view+create+update
   (already true for the seed role).
3. Reports tab: enable **View** on the five `crm_*_list` reports above. Save.
4. Assign the role to a Member (e.g. `b3@lg.com`) if not already.
5. Log in as that member → CRM module shows Leads, Accounts, Contacts, Opportunities, Tasks,
   and Notes.
6. Open Leads → Add Lead visible only if `screen.lead.create` is granted; Edit/row open needs
   `screen.lead.view` (update API needs `screen.lead.update`).

Member without report grants but with screen grants → Notes only (current bug).
Member with report grants but without `screen.lead.create` → list visible, Add hidden / 403.

---

## 5. What not to build

- Changing nav seed / hard-coding sidebar entries in React.
- Granting reports via `GET /reports` (empty for thin admin).
- Editing platform `tenant_admin` / `tenant_member` report grants.
- Portal / account Role Admin.
- Auto-granting reports when a screen permission is ticked (keep the two tabs explicit).

---

## Suggested steps (one per user message)

1. **Confirm API** — `GET /tenant/reports` returns CRM list keys for an admin JWT. Stop if 404.
2. **Reports tab shell** — load catalog + role grants; read-only table joined by `report_id`.
3. **Save diff** — POST / PATCH / DELETE; toasts for 403/409; refetch grants.
4. **Nav invalidation** — after save, invalidate nav + `/auth/me` queries.
5. **Manual verify** — grant CRM lists on `crm_member`, confirm member sidebar.
6. Stop.

## Security checklist

- Role Admin permission required.
- Templates not editable.
- Grant body uses `report_id` only (plus booleans / `row_version`).
- No `tenant_id` in client payloads.
- Sidebar still comes only from `/nav/*`.
