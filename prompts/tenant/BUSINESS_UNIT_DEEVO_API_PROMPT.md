# Prompt — Business units in `deevo_api` (the host that mounts `mtf`)

Paste this whole file into a **chat whose workspace is `deevo_api`**.

`deevo_api` mounts the `mtf` package from `deevo_mt_framework_backend`, and the React app calls
`deevo_api`. `mtf` now has **business units** (stores): staff type a store at login, can switch
store, and their permissions follow the store. That work is finished in
`deevo_mt_framework_backend` on branch **`dev/bu`**, on database **`deevo_app_dev3`**.

This prompt makes `deevo_api` run that version. The routes come from `mtf`, so most of the work
is **checking**, not new code.

Do **not** change `deevo_mt_framework_backend` from here. Do **not** add proxy or wrapper routes for
the new `mtf` endpoints. If something in `mtf` itself is wrong, stop and say so.

Source of truth (read, don't edit):

- `../deevo_mt_framework_backend/prompts/tenant/BUSINESS_UNIT_BACKEND_PROMPT.md` (decisions)
- `../deevo_mt_framework_backend/prompts/tenant/BUSINESS_UNIT_FRONTEND_PROMPT.md` (the API the
  React app will call)
- `../deevo_mt_framework_backend/sql/business_unit_database_design.md` (tables, dev3 scripts)

---

## 0. Adapt before use

| Placeholder | Meaning | Find it in `deevo_api` |
|---|---|---|
| `{API_PREFIX}` | Prefix the `mtf` routers are mounted under | e.g. `app.include_router(mtf_auth_router, prefix="/api/v1")` → `/api/v1` |
| `{MTF_DEP}` | How `mtf` is installed | `pyproject.toml` / `requirements*.txt` (git URL, path or editable install) |
| `{ENV}` | Database settings | `.env` (`DEEVO_MSSQL_DATABASE` / `DB_NAME`) |

---

## 1. Use the new `mtf`

1. Point `{MTF_DEP}` at `deevo_mt_framework_backend` branch `dev/bu`, or the commit the user names.
   For an editable or path install, just make sure that checkout is on `dev/bu`.
2. Reinstall, then confirm that `mtf.tenant.services.business_unit_service` imports.

## 2. Database — **read this first**

`mtf` on `dev/bu` needs **`deevo_app_dev3`**:

- It reads `tenant.business_unit` and writes `business_unit_id` on many tables, which only exist
  in dev3.
- On `deevo_app_dev2`, logins and most tenant writes fail.

Set `{ENV}` to `deevo_app_dev3`.

**dev3 does not have everything dev2 has yet.** These are **not** in dev3:

- the `email`, `crm`, `flow` and `wf` schemas;
- the six DeevoFlow `auth.*` tables;
- the eight `email.*` triggers.

So on dev3:

- Login, `/auth/me`, store switch, staff, roles, reports and nav work.
- Anything in `deevo_api` that reads or writes those schemas fails: CRM screens, mailboxes,
  workflow, and the CRM report procedures.

**Before changing anything, list the `deevo_api` modules, routes and tests that touch those
schemas, and report them.** The database migration for them is a separate task; do not create
those tables from Python.

## 3. Routes the React app will call — confirm they are mounted

These live in `mtf`'s existing routers, so mounting those routers is enough. Check
`{API_PREFIX}/openapi.json`:

| Method + path | Change |
|---|---|
| `POST {API_PREFIX}/auth/login`, `POST {API_PREFIX}/auth/browser/login` | Body gains `business_unit_code` (required for tenant staff); response gains `business_unit_id`, `business_unit_code`, `business_unit_name`, `business_unit_type`, `multi_store` |
| `POST {API_PREFIX}/auth/refresh`, `POST {API_PREFIX}/auth/browser/refresh` | Same new response fields; may end the session with `401` if the store was closed or access removed |
| `POST {API_PREFIX}/auth/session/business-unit` | **New** — switch store (`{"business_unit_code": "…"}`), returns a new token pair |
| `POST {API_PREFIX}/auth/browser/session/business-unit` | **New** — browser variant (refresh token in the cookie) |
| `GET {API_PREFIX}/auth/me` | Gains `business_unit`, `multi_store`, `business_units` |
| `POST {API_PREFIX}/tenant/users/{user_id}/roles` | Body gains optional `business_unit_id` |
| `DELETE {API_PREFIX}/tenant/users/{user_id}/roles/{role_id}` | Gains query `?business_unit_id=` |

If `deevo_api` has **any of these**, update them; otherwise there is nothing to do here:

- its own login, refresh or `/me` route wrapping `mtf`'s: pass the new fields and the request
  field through, and use `mtf`'s response models rather than copies;
- a route allowlist, proxy or gateway rule for `/auth/*`: add the two switch routes;
- CORS or browser-origin settings: the browser switch route uses the same allowed origins as
  `/auth/browser/login`;
- a generated OpenAPI client or schema snapshot: regenerate it.

## 4. Code that uses `mtf` directly — check each item

Search `deevo_api` for each name below. Change only what the search finds.

| Search for | What changed in `mtf` | What to do |
|---|---|---|
| `PermissionResolver(`, `permission_codes(`, `has_permission(`, `report_grants(` with your **own** actor object | The `Actor` protocol now needs `business_unit_id` | Pass `mtf.shared.deps.CurrentUser`, or add `business_unit_id` to the custom actor (the session's unit; `None` = root roles only) |
| `CurrentUser(` built by hand (dependency overrides, background jobs) | New optional `business_unit_id` (default `None`) | Fine for system users. For tenant staff, `None` means only roles held at the root count; pass the unit when acting in a store |
| `get_current_user` | Now also loads `business_unit_id` from the session row | Nothing; use `mtf.shared.deps.get_business_unit_id` in tenant routes that need the store |
| `utc_naive_now`, `_utc_naive_now` | Removed | Use `mtf.shared.clock.utc_now` |
| `apply_soft_delete(` | Takes a model on `StandardColumnsMixin` and calls `row.mark_deleted(by)` | Pass `mtf` model rows only, with keyword `deleted_by=` |
| `.soft_delete(`, `soft_delete_for_tenant(`, `soft_delete_for_account(`, `soft_delete_tenant(` | `deleted_by` is now **required** (was optional) on `TenantUserService`, `TenantAccountUserService`, `TenantAccountService`, `TenantAccountAddressService` and `TenantService` | Always pass the acting user id |
| `invite_token` on `TenantUser` | The plain-text column was dropped in dev3 and removed from the model. dev3 keeps `invite_token_hash`, but `mtf` does not map it | Remove the use. If `deevo_api` really needs invites, stop and report it; mapping `invite_token_hash` is an `mtf` change |
| `append_audit_log(` | New optional `business_unit_id`; defaults to the actor's unit, else the tenant root | Nothing, unless you log for a different tenant than the actor's |
| `create_access_token(` | New optional keyword `business_unit_id` | Nothing |
| Direct inserts into `mtf` tables: `tenant_user`, `tenant_account_user`, `role`, `user_role`, `role_report`, `tenant_account`, `tenant_account_address`, `tenant_setting`, `screen_field_config`, `screen_permission`, `report_definition`, `report_saved_view`, `session`, `audit_log` | dev3 rejects rows without `business_unit_id` (`NOT NULL` or a check) | Prefer `mtf` services. If you must insert, use `mtf.tenant.business_units.root_unit_id(db, tenant_id)`, or `membership_units(...)` for staff memberships, and the `Model.new(by=…)` constructor |
| `user_role` rows for **custom** roles | Held at a **store**, not the root (only tenant-wide `tenant_admin` sits at the root) | Assign through `POST /tenant/users/{id}/roles`, or use the user's default store |

`deevo_api`'s **own** tables (CRM, workflow …) do **not** get `business_unit_id` in this prompt.
That is part of their dev3 migration.

## 5. Tests in `deevo_api`

- Any test that logs in as **tenant staff** must send `"business_unit_code": "MAIN"`. Every new
  staff member can use `MAIN`.
- Tests that log in as portal or system users are unchanged.
- Fixtures that create tenants: onboarding now also creates the root unit `COMPANY` and the store
  `MAIN`. Do not insert tenants by hand.
- Run the suite against dev3. Expect failures only in the modules listed in §2; report them
  separately.

## 6. Smoke test (against the running `deevo_api`)

1. `POST {API_PREFIX}/auth/login` as a tenant admin with `business_unit_code: "MAIN"` → `200`, and
   `business_unit_code` in the body is `MAIN`.
2. The same without a store → `401`, message `Store is required`.
3. `GET {API_PREFIX}/auth/me` with the token → `business_unit.code` is `MAIN` and
   `business_units` is listed.
4. `POST {API_PREFIX}/auth/session/business-unit` with `{"business_unit_code": "COMPANY"}` as the
   admin → `200` and `business_unit_type: "root"`. With `"NOPE"` → `401`,
   `You don't have access to this store`.
5. `POST {API_PREFIX}/auth/refresh` → `200` with the same store.

## 7. Report back

- the `mtf` version installed and the database in use;
- each item from §3 and §4 found, and what was changed;
- the §2 list of `deevo_api` modules that need the not-yet-migrated schemas;
- test results, with the §2 failures separated out;
- the smoke-test results.

## 8. Out of scope

React changes (`BUSINESS_UNIT_FRONTEND_PROMPT.md`), migrating the `email` / `crm` / `flow` / `wf`
schemas to dev3, adding `business_unit_id` to `deevo_api`'s own tables, and any change inside
`deevo_mt_framework_backend`.
