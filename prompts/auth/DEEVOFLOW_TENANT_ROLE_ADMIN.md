# Prompt — DeevoFlow tenant Role Admin (backend)

Paste this whole file into a **Cursor chat whose workspace is `deevoflow_backend`**. Do not
implement this from `deevo_mt_framework_backend`. Do not implement React here.

The Role Admin HTTP already exists in the sibling framework (`mtf.tenant.api.tenant_rbac`).
This product owns: **confirm the mount**, **do not wrap it**, and **prove it over `/api/v1`
with a tenant JWT**. React is a separate prompt:
[`ROLE_ADMIN_FRONTEND_PROMPT.md`](ROLE_ADMIN_FRONTEND_PROMPT.md) (workspace `deevoflow_react`).

Portal (`tenant_account` / account-user roles) is **later**. Do not touch it.

Governing design (read-only, sibling repo):

- `../deevo_mt_framework_backend/mtf/tenant/api/tenant_rbac.py`
- `../deevo_mt_framework_backend/docs/CONVENTIONS.md` (RBAC v3)
- `../deevo_mt_framework_backend/sql/auth_rbac_seed_tenant_catalog_v1.sql`
- `../deevo_mt_framework_backend/sql/rbac_fix_03_screens_flag.sql`

This repo’s rules win on URL prefix, commits, and error codes (`docs/CONVENTIONS.md` in
`deevoflow_backend`).

---

## Product decisions — these win over anything else in this file

1. **Tenant staff only.** JWT `user_scope=tenant`. Do **not** change portal routes, portal
   role grants, or `tenant_account_user` APIs.
2. **Do not implement RBAC in DeevoFlow.** No new SQL, no `app/` copies of permission/role
   tables, no second resolver, no DeevoFlow proxy under `/api/v1/crm/...`.
3. **Do not add role-management handlers in `app/`.** Mount `mtf.tenant` if it is missing.
   React will call `/api/v1/tenant/...` directly.
4. **Gate is `api.auth.role.update`, not membership `admin` alone.** An admin works because
   dual-write maps them to thin `tenant_admin` (Role Admin + admin menus). A member without
   that permission must get **403 `AUTH_FORBIDDEN`**.
5. **JWT never carries grants.** `GET /api/v1/auth/me` already returns `permissions`. Do not
   add them to `TokenResponse`.
6. **Staff membership string stays.** `POST/PATCH /api/v1/tenant/users` still uses
   `role: "admin"|"member"` only. Dual-write: `admin` → `tenant_admin`; `member` → no
   template. Do not write `user_role` yourself.
7. **This work is backend only.** Do not implement the React screen.
8. **Lead gating is a different prompt** ([DEEVOFLOW_RBAC.md](DEEVOFLOW_RBAC.md)). Do not redo
   it here unless those routes are still ungated — then stop and say so, do not mix the two.

**Local:** DeevoFlow depends on the framework as an editable path
(`../deevo_mt_framework_backend`). Uncommitted Role Admin code in the sibling tree is what
this app runs. Shared DB is `deevo_app_dev2` (catalog seed, backfill, and `rbac.screens=on`
already applied).

**Azure later (not this work):** merge framework to `main`, bump the version, `uv lock` here,
apply `rbac_fix_02_permission_catalog.sql`, `auth_rbac_seed_tenant_catalog_v1.sql`,
`rbac_fix_03_screens_flag.sql`, `rbac_fix_05_admin_member_only.sql`, and re-run backfill on
Azure SQL **before** deploying code.

---

## Master instructions

Inspect first: `main.py` (router mounts), OpenAPI at `/openapi.json` or `/docs`, existing
tenant staff tests, `GET /api/v1/auth/me` tests.

Do **not**:

- Redesign or break Generic Report Writer (`mtf.rpt`).
- Implement portal Role Admin.
- Put permission codes in the JWT or login response.
- Drop or stop writing `tenant_user.role`.
- Call `/api/v1/auth/permissions` or `/api/v1/auth/roles` from tenant tests (system scope).
- Add `source_role_id` / copy-from-template.
- POST/PATCH/DELETE `/api/v1/tenant/permissions` (catalog is GET-only).
- Work around MTF gaps (fake grants, skip last-admin, wrap 403 as 200).

Implement **only** the step named in the user message. After each step: files changed, APIs,
tests, assumptions, pending.

Keep today’s error codes. Missing Role Admin grant → **403 `AUTH_FORBIDDEN`**. Edit of a
platform template → **403 `AUTH_ROLE_FORBIDDEN`**. Last-admin → **409 `AUTH_ROLE_CONFLICT`**.

---

## What is already true (verify; do not assume)

| Item | Expected |
| --- | --- |
| App | `http://localhost:8010`, prefix **`/api/v1`** |
| Framework dep | `deevo-mt-framework-backend` path `../deevo_mt_framework_backend` editable |
| Auth mount | `mtf.auth` → `/api/v1/auth` (`GET /me` includes `permissions`) |
| Tenant mount | `mtf.tenant` → `/api/v1/tenant` (staff **and** Role Admin) |
| OpenAPI | `GET /api/v1/tenant/permissions` exists (array of catalog rows) |

If `from mtf.tenant.api.tenant_rbac import router` fails, or OpenAPI has no
`/api/v1/tenant/permissions`, stop and say the sibling checkout does not have Role Admin
steps 3–4 yet.

Expected mount (do not duplicate if already present):

```python
from mtf.tenant.api import router as mtf_tenant_router
app.include_router(mtf_tenant_router, prefix="/api/v1")
```

That single include already has staff routes **and** Role Admin (`permissions`, `roles`,
nested grants, `users/{id}/roles`). Do not include `tenant_rbac.router` a second time.

---

## APIs already in MTF — do not reimplement

Tenant comes from the JWT, never from the body or query.

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/auth/me` | `permissions` is a sorted list of codes |
| GET | `/api/v1/tenant/permissions` | grantable catalog; **no** write |
| GET, POST | `/api/v1/tenant/roles` | POST `{ "code", "name", "description?" }`; `code` `^[a-z][a-z0-9_]*$` |
| GET, PATCH, DELETE | `/api/v1/tenant/roles/{role_id}` | PATCH needs `row_version` (base64). Templates (`is_system`) are read-only |
| GET, POST | `/api/v1/tenant/roles/{role_id}/permissions` | POST `{ "permission_id" }` |
| DELETE | `/api/v1/tenant/roles/{role_id}/permissions/{permission_id}` | catalog id, not grant row id |
| GET, POST | `/api/v1/tenant/users/{user_id}/roles` | POST `{ "role_id" }` |
| DELETE | `/api/v1/tenant/users/{user_id}/roles/{role_id}` | last-admin → 409 |

Catalog row shape (`GET /permissions`): `id`, `code`, `resource_type`, `resource_code`,
`action`, `module_code`, `resource_name`, `sort_order`. Includes CRM screens, WF `menu.*`,
and `api.auth.role.update`. Does **not** include `api.system.role.update`.

---

## What to implement (this work)

1. **Inspect mounts.** List paths under `/api/v1/tenant`. Confirm `permissions` and `roles`.
   Mount `mtf.tenant` only if missing. Do not add `app/` routers.
2. **Product tests against `deevo_app_dev2`** (skip if `DEEVO_SKIP_DB_TESTS`):
   - Login as tenant **admin**. `GET /api/v1/auth/me` includes
     `api.auth.role.update`.
   - Same JWT: `GET /api/v1/tenant/permissions` → **200**, codes include
     `screen.lead.view` and `api.auth.role.update`, and do **not** include
     `api.system.role.update`.
   - Same JWT: `GET /api/v1/tenant/roles` → **200**, includes `is_system=true`
     `tenant_admin` (thin) / empty `tenant_member`.
   - Login as tenant **member**. `GET /api/v1/tenant/permissions` and
     `GET /api/v1/tenant/roles` → **403 `AUTH_FORBIDDEN`**.
   - Admin: `POST /api/v1/tenant/roles` a unique `code`, then
     `PATCH /api/v1/tenant/roles/{tenant_admin_id}` → **403 `AUTH_ROLE_FORBIDDEN`**.
     Clean up the custom role (`DELETE` → 204).
3. Stop. Do not build UI. Do not seed permissions in DeevoFlow SQL.

---

## Suggested steps (one per user message in the DeevoFlow backend chat)

1. **Inspect** — `main.py` mounts and OpenAPI paths. Stop if `/api/v1/tenant/permissions`
   is missing.
2. **Tests** — admin catalog 200; member 403; template PATCH 403. Use existing login helpers.
3. Stop. Hand the React prompt to the frontend chat.

## Security checklist

- Tenant id from JWT only.
- No wrappers under `/crm`.
- No portal changes.
- Member cannot list roles or the catalog.
- Owner `/me` has `api.auth.role.update`.
- OpenAPI documents `/api/v1/tenant/permissions` (not `/api/v1/crm/permissions`).
