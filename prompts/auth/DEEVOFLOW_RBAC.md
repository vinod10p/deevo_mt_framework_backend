# Prompt — DeevoFlow tenant RBAC (product work)

Paste this whole file into a **Cursor chat whose workspace is `deevoflow_backend`**. Do not implement this from `deevo_mt_framework_backend`.

Roles, permissions, and the resolver already exist in the sibling framework (`mtf`). This product owns: confirming the routers are mounted, gating **tenant staff** CRM APIs, and tests. Do **not** copy RBAC tables, models, or `PermissionResolver` into `app/`. Do **not** build role or permission add/edit screens in this work.

Governing design (read-only, sibling repo):

- `../deevo_mt_framework_backend/sql/rbac_database_design.md`
- `../deevo_mt_framework_backend/sql/rbac_development_steps.md`
- `../deevo_mt_framework_backend/sql/auth_rbac_schema_v3.sql`
- `../deevo_mt_framework_backend/sql/auth_rbac_seed_v3.sql`
- `../deevo_mt_framework_backend/sql/auth_rbac_backfill_v3.sql`
- `../deevo_mt_framework_backend/docs/CONVENTIONS.md` (RBAC v3 section)

This repo’s rules win on layering, commits, error codes, and URL prefix (`docs/CONVENTIONS.md` in `deevoflow_backend`).

---

## Product decisions — these win over anything else in this file

1. **Tenant staff only.** Scope is `deevo_crm` / JWT `user_scope=tenant`. Do **not** change portal (`tenant_account`) routes, portal role grants, or account-user APIs.
2. **Do not implement RBAC in DeevoFlow.** No new SQL, no `app/` copies of `mtf.auth.models` permission/role tables, no second resolver.
3. **Do not add role-management routes in `app/`.** Catalog and assignment HTTP already live on the mounted MTF routers. React (later) calls those URLs directly. Do not wrap them in a DeevoFlow proxy.
4. **Do not build add/edit screens** for roles or permissions in this backend work. Membership `role` (`owner` / `admin` / `member` / `viewer`) on the existing tenant-user APIs is enough to test.
5. **Staff membership string stays master.** Existing create/update/delete of tenant users still send `role`. Dual-write to `auth.user_role` already runs inside MTF `TenantUserService`. Do not write `user_role` yourself.
6. **JWT never carries grants.** UI (later) reads `GET /api/v1/auth/me`. Backend still authorizes every request with the resolver. Do not add `permissions` to `TokenResponse`.
7. **Lead (and other screens) keep `require_screen_permission`.** Do **not** wrap those routes with a second `require_permission("screen.lead.*")`.
8. **This work is backend only.** Do not implement React. After `/me` is confirmed, document the JSON fields the frontend will use.

**Local:** DeevoFlow depends on the framework as an editable path (`../deevo_mt_framework_backend`). Uncommitted RBAC code in the sibling tree is what this app runs. Shared DB is `deevo_app_dev2` (schema, seed, and backfill already applied).

**Azure later (not this work):** merge framework RBAC to `main`, bump the framework version, `uv lock` here, apply `auth_rbac_schema_v3.sql` then seed then backfill on Azure SQL **before** deploying code.

---

## Master instructions

Inspect this codebase first: `main.py` (router mounts), Lead routes (`app/crm/api/lead.py`, `lead_screen.py` if present), existing `require_scope("tenant")`, tests that hit `/api/v1/auth/me` and CRM leads.

Reuse FastAPI, SQLAlchemy, `require_scope("tenant")`, `get_tenant_id`, existing `LeadService`.

Do **not**:

- Redesign or break Generic Report Writer (`mtf.rpt` mount).
- Implement portal RBAC, `menu.*`, or a dynamic menu.
- Put permission codes in the JWT or login response.
- Drop or stop writing `tenant_user.role`.
- Call system-scope catalog APIs from tenant routes.
- Work around known MTF gaps listed at the bottom (copy extra grants in product SQL, fake export checks, etc.).

Implement **only** the step named in the user message. After each step: files changed, APIs, tests, assumptions, pending.

Keep today’s error codes. Tenants on RBAC get `403 AUTH_FORBIDDEN` from `require_screen_permission`; tenants still on `txn.screen_permission` get `403 SCREEN_FORBIDDEN`. Hidden reports stay `404 REPORT_NOT_FOUND`.

---

## How this is implemented in the framework (read this before coding)

Grants-only: if no role grants it, the user cannot do it. There are no deny rows.

### Tables (all in `auth`, owned by MTF)

| Table | Job |
| --- | --- |
| `permission` | Catalog. `code` = `resource_type.resource_code.action` (e.g. `screen.lead.view`) |
| `role` | Named bundle. `tenant_id` NULL = platform template (`is_system=1`). Set = tenant custom role |
| `role_permission` | Which permission codes a role grants |
| `user_role` | Which roles a user holds, and **where** (tenant vs account vs system) |
| `role_report` | Per-tenant report `can_view` / `can_export` by role |
| `default_role_report` | Platform defaults, **copied** at tenant create / backfill, never read at runtime |

`resource_type`: `menu` \| `screen` \| `api`. `action`: `view` \| `create` \| `update` \| `delete` \| `export` \| `import` \| `approve`. `user_scope` must match across user, role, and permission (composite FKs). A tenant-scope Lead permission **cannot** sit on an account-scope role.

### How a tenant staff request is authorized

```
HTTP request
  → JWT (scope + tenant_id only; no permission codes)
  → PermissionResolver (one instance per request, memoized on request.state)
  → active tenant_user for (user_id, tenant_id)
  → live user_role in that tenant with account_id IS NULL
  → union of role_permission codes
  → require_permission / require_screen_permission
```

Inactive membership → empty set (no access), even if `user_role` rows remain.

Portal and system branches exist in the resolver; **do not use them in this work**.

Missing catalog permission → `403 AUTH_FORBIDDEN`. Hidden report GET/`/run` → `404 REPORT_NOT_FOUND` (not 403), so the caller cannot tell the report exists.

### Dual-write (already in MTF; you do not call this)

On every tenant-user create/update/soft-delete, MTF upserts `user_role`:

| `tenant_user.role` | Platform `auth.role.code` |
| --- | --- |
| `owner`, `admin` | `tenant_admin` |
| `member`, `viewer` | `tenant_member` |

If the template role is missing, the membership write fails (`409`). Sync only replaces those **template** roles; extra custom roles assigned via `/api/v1/tenant/users/{id}/roles` survive a name/phone edit. Deleting the membership still revokes every assignment in that place.

### Screen gates (`require_screen_permission`)

Product routes keep this import. MTF chooses one path, not both:

- Tenant has RBAC for that screen when live `auth.permission` has `resource_type=screen` and `resource_code={key}` **and** the tenant has a live `user_role` row.
- Then check `screen.{key}.{action}` only: `view`→`view`, `add`→`create`, `edit`→`update`, `delete`→`delete`. Deny → `403 AUTH_FORBIDDEN`.
- Else fall back to `txn.screen_permission`. Deny → `403 SCREEN_FORBIDDEN`.
- An RBAC deny does **not** consult `screen_permission` or `screen.allow_*`.
- `GET /api/v1/screens/{screen_key}` uses the same branch for the `permissions` object.

Backfilled tenants on `deevo_app_dev2` take the RBAC path for `lead`.

### What is already seeded

Platform roles: `tenant_admin`, `tenant_member` (plus portal/system templates you will not use here).

| Role | Screen / API grants |
| --- | --- |
| `tenant_admin` | `screen.lead.view\|create\|update\|delete\|export`, `api.auth.role.update` |
| `tenant_member` | `screen.lead.view` only |

Last-admin means at least one live assignment holds `api.auth.role.update` (not `manage`; the schema check does not allow `manage`). Escalation: an actor cannot grant a permission code they do not hold. Tenant assignment routes are still gated with JWT tenant + membership `owner`/`admin`, not `require_permission("api.auth.role.update")` yet.

---

## What is already true in DeevoFlow (verify; do not assume)

| Item | Expected |
| --- | --- |
| App | `http://localhost:8010`, prefix **`/api/v1`** |
| Framework dep | `deevo-mt-framework-backend` path `../deevo_mt_framework_backend` editable |
| Auth mount | `mtf.auth` → `/api/v1/auth` (login, refresh, **`GET /me`**, users) |
| Tenant mount | `mtf.tenant` → `/api/v1/tenant` (tenants, staff, **roles**, accounts) |
| Reports mount | `mtf.rpt` → `/api/v1/reports` (already filtered by `role_report`) |
| Txn mount | `mtf.txn` → `/api/v1/screens/{screen_key}` — confirm; mount if missing, do not duplicate |
| Lead routes | Existing `/api/v1/crm/leads` and/or `/api/v1/crm/lead-screen` — **gate these**; do not invent a new permission module |

If `from mtf.txn.api.deps import require_screen_permission` fails, stop and say the sibling checkout does not have step-10 screen access yet.

---

## What to implement in DeevoFlow (this work)

1. Confirm mounts. Do not remount a router that is already included.
2. Gate **tenant** Lead (and lead-screen if present) with `require_scope("tenant")` plus `require_screen_permission`.
3. Confirm `GET /api/v1/auth/me` already returns `permissions` and `reports` from MTF. Do not re-assemble grants in DeevoFlow. Add a product test if none exists.
4. Tests: owner/admin can write Lead; member/viewer cannot (`403 AUTH_FORBIDDEN` on a backfilled tenant); `/me` for a member includes `screen.lead.view` and does not include `screen.lead.create`.

Out of scope (do not do in this prompt):

- Role / permission admin UI or extra `app/` CRUD.
- Portal customers.
- New screen keys besides Lead (document the pattern only).
- Export enforcement (`screen.lead.export` is seeded but no helper operation is required on Lead yet).
- Changing `tenant_admin` / `tenant_member` grants (that is system catalog / SQL).

---

## APIs to **call** (already in MTF) — do not reimplement

DeevoFlow prefix: `/api/v1`. Tenant comes from the JWT, never from the body.

### Current user (every CRM session)

`GET /api/v1/auth/me`

Extra fields (already on `UserMeRead`):

```json
{
  "role": "admin",
  "permissions": ["api.auth.role.update", "screen.lead.create", "screen.lead.view", "..."],
  "reports": [
    { "report_key": "crm_lead_list", "can_view": true, "can_export": true }
  ]
}
```

- `permissions`: sorted catalog codes the resolver loaded for this request.
- `reports`: only rows with `can_view`. Use `report_key` in the UI; backend catalog/`/run` still enforce.
- `role` is still the membership string (`owner`/`admin`/`member`/`viewer`), not `tenant_admin`.

Login / refresh `TokenResponse` must **not** gain these fields.

### Staff membership (already dual-writes)

Existing tenant user create/update/delete. Body still uses `role: "owner"|"admin"|"member"|"viewer"`. Do not change the payload.

### Tenant assignment (call later from React; do not wrap in `app/`)

Gated with JWT tenant + owner/admin membership.

| Method | Path | Body |
| --- | --- | --- |
| GET, POST | `/api/v1/tenant/roles` | POST `{ "code", "name", "description?" }` — `code` `^[a-z][a-z0-9_]*$` |
| GET, PATCH, DELETE | `/api/v1/tenant/roles/{role_id}` | PATCH needs `row_version`. Cannot edit platform (`is_system`) roles. Last-admin deactivate → `409 AUTH_ROLE_CONFLICT` |
| GET, POST | `/api/v1/tenant/roles/{role_id}/permissions` | POST `{ "permission_id" }` |
| DELETE | `/api/v1/tenant/roles/{role_id}/permissions/{permission_id}` | |
| GET, POST | `/api/v1/tenant/roles/{role_id}/reports` | POST `{ "report_id", "can_view", "can_export" }` |
| PATCH, DELETE | `/api/v1/tenant/roles/{role_id}/reports/{report_id}` | PATCH needs `row_version` |
| GET, POST | `/api/v1/tenant/users/{user_id}/roles` | POST `{ "role_id" }` — **staff only** (`account_id` null) |
| DELETE | `/api/v1/tenant/users/{user_id}/roles/{role_id}` | |

Do not implement these handlers in DeevoFlow. They are already on `mtf.tenant.api`.

### System catalog (do not call from tenant CRM)

`/api/v1/auth/permissions`, `/api/v1/auth/roles`, nested `/permissions` and `/default-reports`. JWT `user_scope=system` only (deevo_admin). POST permission composes `code` from `{resource_type, resource_code, action, user_scope}` — do not send `code`.

---

## Python to use in Lead routes

```python
from mtf.shared.deps import require_scope
from mtf.txn.api.deps import require_screen_permission

Depends(require_scope("tenant"))
Depends(require_screen_permission("lead", "view"))   # GET  → screen.lead.view
Depends(require_screen_permission("lead", "add"))    # POST → screen.lead.create
Depends(require_screen_permission("lead", "edit"))   # PATCH → screen.lead.update
Depends(require_screen_permission("lead", "delete")) # DELETE → screen.lead.delete
```

If txn is not mounted yet:

```python
from mtf.txn.api import router as mtf_txn_router
app.include_router(mtf_txn_router, prefix="/api/v1")
```

Non-screen tenant APIs (settings, etc.), when you add a catalog code later:

```python
from mtf.shared.deps import require_permission
Depends(require_permission("api.something.update"))
```

Do not use `require_permission("screen.lead.view")` on Lead — the screen helper already switches to RBAC.

---

## Expected behaviour on `deevo_app_dev2` (backfilled tenant)

| Caller | Lead GET/list | Lead POST/PATCH/DELETE |
| --- | --- | --- |
| Tenant `owner` / `admin` | 200 | 200 / 204 |
| Tenant `member` / `viewer` | 200 | **403 `AUTH_FORBIDDEN`** |
| No Bearer | 401 | 401 |

Reports the user’s roles cannot view: omitted from `GET /api/v1/reports`; GET-by-key and `/run` return **404**.

---

## New tenant screen later (do not implement now)

1. System catalog: permission rows `screen.{key}.view|create|update|delete` with `user_scope=tenant`.
2. Grant on `tenant_admin` (and `tenant_member` if members should see it).
3. Gate product routes with `require_screen_permission("{key}", ...)`.
4. Until catalog + tenant `user_role` exist, the helper stays on `txn.screen_permission`.

---

## Known MTF gaps — do not work around in DeevoFlow

- Tenant-owned reports start with no `role_report` rows; the first grant can 403 on escalation.
- Tenant admins cannot edit report grants on portal template roles (irrelevant for this tenant-staff work).
- `can_export` / `screen.lead.export` are stored but not enforced on an export endpoint.
- Saved-view **management** still uses `tenant_user.role`.
- Dual-write of membership `is_active` into backfilled `user_role` is incomplete; last-admin may count inactive members. Do not patch that here.

---

## Suggested steps (one per user message in the DeevoFlow chat)

1. **Inspect mounts** — `main.py`: auth, tenant, reports, txn. List paths. Do not add duplicate routers. Stop if `require_screen_permission` cannot be imported.
2. **Gate Lead** — add `require_screen_permission` to existing Lead and lead-screen routes (keep `require_scope("tenant")`). Tests: admin write succeeds; member write is 403 `AUTH_FORBIDDEN`.
3. **Confirm `/me`** — test that a tenant JWT gets `permissions` (list of strings) and `reports` (list of `{report_key, can_view, can_export}`). Do not change `TokenResponse`.
4. Stop. Role admin UI, portal, and new screens are later prompts.

## Security checklist

- Tenant id from JWT only.
- No permission codes in login/refresh tokens.
- No product copy of the resolver.
- Member cannot write Lead on a backfilled tenant.
- OpenAPI still documents the existing Lead paths; new role routes must **not** appear under `/api/v1/crm/...`.
