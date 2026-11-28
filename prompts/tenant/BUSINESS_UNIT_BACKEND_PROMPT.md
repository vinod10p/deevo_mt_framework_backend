# Backend prompt — Business units: store on login, store switch, store-aware permissions

Workspace: **`deevo_mt_framework_backend`**, branch **`dev/bu`**. Database: **`deevo_app_dev3`**.
Backend only. The React screens are a separate prompt for the frontend repo
(`BUSINESS_UNIT_FRONTEND_PROMPT.md`, written in this repo, implemented there with its own tool).

Governing design: [`../../sql/business_unit_database_design.md`](../../sql/business_unit_database_design.md).
Default units SQL: [`../../sql/dev3_10_business_unit_defaults.sql`](../../sql/dev3_10_business_unit_defaults.sql).

Not in this prompt (later prompts): the `TenantBUMixin` / repository **read filter** for business
tables, business-unit admin CRUD screens, reports filtered by store, inventory and email modules
(the `email`, `crm`, `flow`, `wf` schemas and six DeevoFlow `auth.*` tables are not in dev3 yet;
mailbox endpoints and tests failing on dev3 are expected).

---

## Product decisions — these win over anything else in this file

1. **A tenant has many business units.** Each tenant has exactly one `bu_type = 'root'` unit
   (code `COMPANY`, name = tenant name) and at least one store (first one code `MAIN`).
   Logic checks **`bu_type` only**, never `code` or `name`.
2. **Login screen** (shared URL): Company, **Store**, Email, Password — all typed text fields.
   No dropdown and no public lookup of stores. The frontend prefills Store with the last store
   used on that device.
3. **Store is required for every client** (`web`, `desktop`, `mobile_*`, `api`) when the user
   is tenant staff (`user_scope = tenant`). No backend fallback.
4. **Portal users** (`tenant_account`) and **system users** do not send a store. If a portal
   user sends one it is ignored; portal sessions sit at the tenant's root unit. System sessions
   have no unit.
5. **Store is checked after the password and the tenant membership**, like the company today.
   A wrong store is **not** a password guess (does not count toward throttling or lockout).
6. **One error for every store failure** — unknown code, inactive/deleted unit, unit of another
   tenant, unit the user may not use:
   `401 AUTH_UNAUTHORIZED`, message **"You don't have access to this store"**.
   Missing/blank store: `401 AUTH_UNAUTHORIZED`, message **"Store is required"**.
   Both are audited as `login_failed` with reasons `store_required` / `store_denied`.
7. **Which stores a staff user may log in to:**

   | User | Accepted store codes |
   | --- | --- |
   | Has any live role at the **root** unit | Any active non-root unit of the tenant, **or** the root code (= "All stores" mode, read-only for store-owned data) |
   | Has roles at particular stores only | Those stores |
   | Has roles at both | Union of the two rows above |
   | **Member with no live roles** | Only `tenant_user.default_business_unit_id`; if that is NULL, the active unit with code `MAIN`. Logs in with no permissions (same as today) |

8. **Code matching:** trimmed, case-insensitive, within the tenant from the request only.
9. **Effective permissions in a session** = roles assigned at the root unit **+** roles assigned
   at the session's unit. In "All stores" mode (session unit = root) only root roles count.
10. **Root assignment rule:** a tenant-scope role may be assigned at the root unit only if
    `role.is_tenant_wide = 1` (platform `tenant_admin` is tenant-wide). Enforced on **new**
    assignments only; rows migrated to root stay valid (see open item Q1).
11. **The session row is the source of truth** for the current unit. The JWT carries
    `business_unit_id` for convenience, but `get_current_user` reads the session's value.
12. **Store switch** is an API (`POST /auth/session/business-unit`) using the same access rules
    as login. It updates the session and returns a new access token; the old access token stops
    working immediately (same rotation rule as refresh).
13. **Refresh** re-checks the session's unit: still active and still allowed for the user. If
    not, the session ends (`401 AUTH_UNAUTHORIZED`, reason `store_access_removed`). No fallback.
14. **Membership dual-write** (`mtf/auth/services/membership_rbac.py`) writes new
    `user_role` rows at the tenant's **root** unit (portal and staff templates).
15. **Onboarding** (`TenantService.create_tenant`) creates the root unit and the `MAIN` store in
    the same transaction. New staff get `tenant_user.default_business_unit_id = MAIN`.
16. **dev3 already enforces business units.** Every insert into a tenant table must set
    `business_unit_id`, or the database rejects it (`NOT NULL` or a `CK_*_tenant_bu` /
    `CK_*_scope` check). Until store-owned data exists, **every tenant row is written at the
    tenant's root unit**, except `auth.session` (the session's unit) and `audit.audit_log`
    (the acting session's unit, else root). Platform / system rows keep `business_unit_id = NULL`.

---

## Master instructions

- Inspect first: `mtf/auth/services/session_service.py`, `mtf/auth/api/session.py`,
  `mtf/auth/schemas/session.py`, `mtf/shared/deps.py`, `mtf/shared/security.py`,
  `mtf/auth/services/permission_resolver.py`, `mtf/auth/services/membership_rbac.py`,
  `mtf/auth/services/me.py`, `mtf/tenant/services/tenant_service.py`,
  `mtf/tenant/api/tenant_rbac.py`, `tests/auth/`.
- **Implement only the step named in the user message.** After each step report: files changed,
  APIs changed, tests added/run, assumptions, pending.
- Do not commit or push. Do not touch other repos.
- Keep today's error codes and helpers (`mtf/shared/exceptions.py`). No new error-code prefixes.
- Do not put permission codes in the JWT or the login response.
- Do not change portal login rules beyond decision 4.
- Do not drop or stop writing `tenant_user.role` / `tenant_account_user.role`.
- Models must match the dev3 DDL exactly. If a column in this prompt is missing from dev3,
  **stop and say so** — do not add DDL from Python.
- Unit tests for logic; integration tests (live DB) where the existing suite has them.

---

## Database columns this work relies on (dev3 — verified in step 0)

`tenant.business_unit`: `id`, `tenant_id`, `parent_id`, `bu_type`, `code`, `name`, address
fields, `timezone`, `currency`, `sort_order`, standard columns.

`business_unit_id` on existing tables and the rule dev3 enforces:

| Table | dev3 rule | Value written by this work |
| --- | --- | --- |
| `auth.tenant_user` | `NOT NULL` (+ `default_business_unit_id` NULL) | root; default = `MAIN` |
| `auth.tenant_account_user` | `NOT NULL` | root |
| `auth.role_report` | `NOT NULL` | root |
| `tenant.tenant_account` | `NOT NULL` | root |
| `tenant.tenant_account_address` | `NOT NULL` | root (same as its account) |
| `tenant.tenant_setting` | `NOT NULL` | root |
| `txn.screen_field_config` | `NOT NULL` | root |
| `txn.screen_permission` | `NOT NULL` | root |
| `auth.session` | `CK_session_tenant_bu`: set for tenant / portal, NULL for system | session's unit |
| `audit.audit_log` | `CK_audit_log_tenant_bu`: set when `tenant_id` set | acting session's unit, else root |
| `auth.role` | `CK_role_tenant_bu`: set when `tenant_id` set | root (tenant roles) |
| `auth.user_role` | `CK_user_role_scope_shape`: set for tenant / portal rows | root (store later, step 8) |
| `rpt.report_definition` | `CK_report_definition_scope`: set for `scope_type = 'tenant'` | root |
| `rpt.report_saved_view` | `CK_report_saved_view_scope`: set for `tenant` / `user` scope | root |

Also new: `auth.role.is_tenant_wide`. Already removed from the model: `tenant_user.invite_token`
(dropped in dev3).

---

## Steps

### Step 0 — Verify the environment ✅ done (Nov 25, 2026)
- `.env` points at `deevo_app_dev3`.
- All columns above exist in dev3; every tenant has `COMPANY` + `MAIN`; all `user_role` rows are
  at root; every live staff member has `default_business_unit_id`; only `tenant_admin` is
  tenant-wide.
- `tenant_user.invite_token` removed from the model (dropped in dev3).
- Finding: dev3 rejects tenant inserts that lack `business_unit_id` (decision 16), so tenant and
  portal login, onboarding and most tenant writes fail on dev3 until step 2.

### Step 1 — Models ✅ done (Nov 26, 2026)
Done as below, plus: standard columns now come from `mtf/shared/model_columns.py`
(`StandardColumnsMixin`, `RecordStateMixin`, `ulid()`, `business_unit_fk()`); the 15 models
touched here use it (the other model files still repeat the columns — convert when touched).
`deleted_at` is now mapped on every touched table. Integration tests run SQL scripts through
`tests/sql_scripts.py`, which strips every `USE` line (a `USE [deevo_app_dev2]` hidden after
the header comment used to switch pooled connections to dev2).
Findings for step 2: dev3 has `CK_<table>_deleted` on every table, so every soft delete must
set `deleted_at` and `deleted_by`; dev3 has **no triggers** (dev2's
`TR_tenant_setting_rbac_screens_one_way` and the RBAC triggers were not recreated).

- New `mtf/tenant/models/business_unit.py` (`BusinessUnit`), exported from `mtf.tenant.models`.
- Map `business_unit_id` on all 14 models in the table above (nullability exactly as dev3),
  plus `TenantUser.default_business_unit_id` and `Role.is_tenant_wide`.
- Update the matching Pydantic read schemas to expose `business_unit_id` where the table's
  other keys are exposed.
- Model tests: columns, nullability, FK targets, `bu_type` values. Fix existing model tests that
  list exact column sets.

### Step 2 — Write the root unit on every insert ✅ done (Nov 26, 2026)
Done as below. Shared pieces: `mtf/tenant/business_units.py` (`root_unit_id`,
`first_store_id`, `membership_units`, `create_default_units` — flushes the units at once,
because rows referencing a unit have no ORM relationship to order them),
`mtf/shared/clock.py` (`utc_now`, replaced 11 copies), `Model.new(by=…)` and
`row.mark_deleted(by)` on the standard mixin (every soft delete now sets `deleted_at`;
`deleted_by` is required). `User`, `Tenant`, `Permission`, `RolePermission`,
`DefaultRoleReport` moved onto the mixin. Tests: `tests/cleanup.py` replaces six copied
clean-up helpers; `tests/conftest.py` answers unit lookups for mock sessions.
dev3 result: 1070 passed, 40 failed — none from business units. Remaining: missing `rpt`
procedures in dev3 (dev2 has 38, dev3 0). Stale tests (retired `tenant_member` template,
`screen.lead.view` for admins, last-admin rule) were updated to the admin/member model
(`THIN_ADMIN_PERMISSIONS` in `tests/tenant/rbac_fixtures.py`). The six tests that re-run dev2
SQL scripts are not run on dev3.

Goal: everything that worked on dev2 works on dev3 again. No store filtering, no login change.
- `BusinessUnitService.get_root(tenant_id)` and `get_main(tenant_id)` (small, cached per
  request / session object), used by the writers below.
- `TenantService.create_tenant`: create root (`COMPANY`, name = tenant name, address and
  timezone from the tenant) and store `MAIN` in the same transaction, **before** any other
  tenant row or audit row is written (decision 15).
- Every service that inserts into a `NOT NULL` / checked table in the table above sets
  `business_unit_id = root` (find them with a search for each model's constructor / `add`).
  Includes `membership_rbac` dual-write (`user_role`, decision 14), `copy_default_role_reports`
  (`role_report`), tenant roles, tenant settings (incl. `rbac.screens`), customers and their
  addresses, portal and staff memberships (staff also get `default_business_unit_id = MAIN`),
  screen field config, screen permissions, tenant reports and saved views.
- **Interim session unit** (replaced in step 4): staff → `tenant_user.default_business_unit_id`
  (else root); portal → root; system → NULL.
- `append_audit_log` gains `business_unit_id`. When not passed and `tenant_id` is set: use the
  acting session's unit if the source has a session, else the tenant's root. NULL only when
  `tenant_id` is NULL.
- Tests: each writer writes root; onboarding creates exactly one root and one `MAIN`; audit rows
  carry a unit; the integration suite that failed in step 0 (`test_session_revocation_integration`,
  `test_login_rate_limit_integration`, onboarding and RBAC integration tests) passes on dev3.
  Report any remaining failures that are not mailbox / `email.*`.

### Step 3 — Business unit service ✅ done (Nov 26, 2026)
Done: `BusinessUnitService` with `AllowedUnits` (`has_root_role`, `store_ids`, `allows(unit)`)
and one `StoreAccessError(reason)` for `store_required` / `store_denied` (message per
decision 6; step 4 maps it to `401 AUTH_UNAUTHORIZED`). A member with no live roles falls back
to `default_business_unit_id`, else the active store with code `MAIN` (decision 7 as written;
confirmed Nov 26, 2026 as the one exception to decision 1). Tests: `tests/tenant/test_business_unit_service.py`
(rules) and `..._integration.py` (dev3: case/whitespace, inactive, deleted, other tenant).

`mtf/tenant/services/business_unit_service.py`:
- `get_root(tenant_id)`, `get_active_by_code(tenant_id, code)` (trimmed, case-insensitive),
  `list_active(tenant_id)`.
- `allowed_units_for_staff(tenant_id, user_id) -> AllowedUnits` implementing decision 7
  (root-role flag, set of store ids, fallback unit for members with no roles).
- `resolve_login_unit(tenant_id, user_id, code) -> BusinessUnit` — raises a domain error the
  session service maps to decision 6.
- Unit tests for every row of decision 7, plus: inactive unit, deleted unit, other tenant's code,
  root code without root role, case and whitespace in the code.

### Step 4 — Login ✅ done (Nov 26, 2026)
Done: staff must send `business_unit_code`; `StoreAccessError` → `_reject_login` (reasons
`store_required` / `store_denied`, not throttled). Portal sessions use the root unit. The token
has claim `business_unit_id`; login responses (and `/auth/browser/login`) have
`business_unit_id/code/name/type` and `multi_store`; the `login` audit row has
`new_values.business_unit_id`. Live tests log in through one helper, `tests/staff_login.py`
(store `MAIN` by default). Tests: `tests/auth/test_login_store_integration.py`.
Not covered by a live test: a portal user sending a store (ignored by design).

- `LoginRequest.business_unit_code: str | None = Field(None, max_length=30)`.
- In `SessionService.login`, tenant branch, after the membership check: required check
  (decision 3), then `resolve_login_unit`. Failures go through `_reject_login` with reasons
  `store_required` / `store_denied` (not in `_GUESS_REASONS`).
- Portal branch: session unit = tenant root. System branch: none.
- Save `business_unit_id` on the session; add it to `audit_log` `new_values` for `login`.
- `create_access_token(..., business_unit_id=...)` adds claim `business_unit_id` when set.
- `AccessTokenResponse` gains: `business_unit_id`, `business_unit_code`, `business_unit_name`,
  `business_unit_type` (`root` / `store` / …), `multi_store: bool` (tenant has more than one
  active non-root unit). Same fields on `/auth/browser/login`.
- Tests: decisions 3–8 over `/auth/login` and `/auth/browser/login`; throttle not incremented
  by store failures; audit reasons written.

### Step 5 — Current user and refresh ✅ done (Nov 26, 2026)
Done: `get_current_user` reads `session.business_unit_id` in its existing session query (the
token claim is ignored). `get_business_unit_id` (tenant scope) → 401 "Store context required"
when the session has none. Refresh calls `BusinessUnitService.recheck_session_unit`; a store
that is inactive, deleted or no longer open to the user ends the session
(`revoke_reason = store_access_removed`, 401 "Invalid refresh token"). Portal refresh returns the
root unit. Refresh responses carry the same business unit fields as login. Tests:
`tests/shared/test_current_user_session.py`, `tests/auth/test_refresh_membership.py`,
`tests/auth/test_login_store_integration.py` (refresh section).
Note: staff sessions created before step 4 have the interim unit (default store); refresh
re-checks them like any other.

- `CurrentUser.business_unit_id: str | None`, loaded from the session row in the same query
  `get_current_user` already runs (no extra round trip).
- New dependency `get_business_unit_id` (tenant scope; 401 if missing).
- `SessionService.refresh`: re-check decision 13; keep the unit; new access token carries it.
  Refresh response has the same business unit fields as login.
- Tests: role removed at the session's store → refresh ends the session; unit deactivated →
  same; normal refresh keeps the unit.

### Step 6 — Store-aware permissions and `/me` ✅ done (Nov 26, 2026)
Done: the resolver's tenant role query joins `tenant.business_unit` and keeps `user_role` rows
held at a `bu_type = 'root'` unit or at the session's unit (no root-id lookup, so an unknown
tenant still resolves to nothing). `business_unit_id` is in `Actor` and the cache key; a caller
with no unit gets root roles only.
`/me` adds `business_unit`, `multi_store` and `business_units`
(`BusinessUnitService.list_open_to_staff`; empty for portal users). Tests:
`tests/auth/test_permission_resolver.py`, `tests/auth/test_store_permissions_integration.py`;
`tests/business_unit_fixtures.grant_store_role` now takes permission codes.

- `PermissionResolver._role_ids_stmt` (tenant branch): only `user_role` rows whose
  `business_unit_id` is the root unit or the actor's `business_unit_id` (decision 9).
  Include `business_unit_id` in the resolver's cache key and in the `Actor` protocol.
- `GET /auth/me` adds: `business_unit` (`id`, `code`, `name`, `bu_type`), `multi_store`,
  `business_units` (the units the user may switch to: `id`, `code`, `name`, `bu_type`,
  sorted by `sort_order`, root first only if allowed).
- Tests: a role at KNIGHTSBRIDGE grants nothing in MAYFAIR; a root role grants in both;
  "All stores" mode ignores store roles; `/me` lists exactly the allowed units.

### Step 7 — Switch store ✅ done (Nov 26, 2026)
Done: `SessionService.switch_business_unit` (login rules via `resolve_login_unit`), routes
`POST /auth/session/business-unit` and `/auth/browser/session/business-unit` (cookie, browser
shape), tenant scope only (403 otherwise). A switch issues a **new access and refresh pair**
(shared `_rotate_tokens` with refresh): the session keeps only token hashes, so it cannot
return the old refresh token. Audit: dev3's `CK_audit_log_action` has no switch action, so it
is `action = 'update'` on `auth.session` with `new_values.event = 'business_unit_switch'` and
the old / new unit (confirmed Nov 26, 2026). Note for the frontend: a denied switch is a
**401** with "You don't have access to this store" — not a session expiry. Tests:
`tests/auth/test_business_unit_switch.py`, `tests/auth/test_store_switch_integration.py`.

- `POST /auth/session/business-unit` body `{ "business_unit_code": "MAYFAIR" }`, tenant scope.
- Same rules as login (decisions 6–8). On success: update `session.business_unit_id`, rotate
  the access token hash on the session, audit `business_unit_switch` (old and new unit), return
  the same body as refresh (`/auth/browser/...` variant returns the browser shape, no refresh
  token in the body).
- Tests: allowed switch; denied switch (same 401 message, session unchanged); old access token
  rejected after a switch; portal and system users get 403 `AUTH_FORBIDDEN`.

### Step 8 — Assign a role at a store ✅ done (Nov 26, 2026)
Done: `UserRoleCreate.business_unit_id` (optional). **Omitted:** a tenant-wide role goes to the
root; any other role goes to the user's **default store** (else `MAIN`) — confirmed Nov 26,
2026, so today's Role Admin screen keeps working. **Named:** must be an active unit of the
tenant (404 `TENANT_BUSINESS_UNIT_NOT_FOUND`); the root only for tenant-wide roles (409
`AUTH_ROLE_CONFLICT` "This role can only be assigned to a store"). `DELETE
/tenant/users/{user_id}/roles/{role_id}?business_unit_id=…` — the store may be omitted when the
role is held at one unit; 409 when held at several. Tests: `tests/auth/test_rbac_assignment.py`,
`tests/auth/test_store_role_assignment_integration.py`.
Note: tenants cannot mark custom roles tenant-wide yet (no field in `TenantRoleCreate`), so only
platform `tenant_admin` can be held at the root through this API (see Q1).

(Onboarding and dual-write at root are done in step 2.)
- `POST /tenant/users/{user_id}/roles`: optional `business_unit_id` in `UserRoleCreate`
  (default root). Reject a unit of another tenant (404) and a non-tenant-wide role at root
  (`409 AUTH_ROLE_CONFLICT`, "This role can only be assigned to a store"). List and delete
  include `business_unit_id`; the unique key includes it, so one role can be held at two stores.
- Tests: assignment rules above; the same role held at two stores; revoking at one store
  leaves the other.

### Step 9 — Frontend prompt ✅ done (Nov 26, 2026)
Done: [`BUSINESS_UNIT_FRONTEND_PROMPT.md`](BUSINESS_UNIT_FRONTEND_PROMPT.md) for `deevoflow_react`
(login Store field, remembered store, errors, header switcher, refresh, role assignment at a
store, acceptance checks). `tests/tenant/test_business_unit_frontend_prompt.py` fails if a
field name, route or store message in the prompt drifts from the code.

Write `prompts/tenant/BUSINESS_UNIT_FRONTEND_PROMPT.md` (in this repo) from the final API:
login request/response fields, error messages, "remember store on this device", the store
switcher using `/me.business_units` and the switch endpoint, hiding store UI when
`multi_store = false`. Do not implement React.

---

## Open items for review

| # | Question | Proposed |
| --- | --- | --- |
| Q1 | Existing custom-role assignments were migrated to root, but custom roles default to `is_tenant_wide = 0`. Leave them, move them to `MAIN`, or mark those roles tenant-wide? | ✅ **Decided Nov 26, 2026: option B — move them to a store.** `sql/dev3_12_move_custom_roles_to_store.sql` moves live staff assignments of non-tenant-wide roles from the root to the member's default store (else `MAIN`); applied to dev3: 30 moved, 0 retired, 0 left at root; portal and `tenant_admin` rows untouched. Logged in `auth.user_role_store_move_log` (undo SQL at the end of the script). Effect: those users keep their permissions at that store but can no longer log in to "All stores". Tenants still cannot create tenant-wide custom roles (no field in `TenantRoleCreate`) |
| Q2 | Should root ("All stores") mode be offered to root-role users at login, or only through the switcher? | Both: typing the root code at login is allowed for root-role users |
| Q3 | Token claim name: `business_unit_id` or a short `bu`? | `business_unit_id`, matching `tenant_id` / `account_id` |
