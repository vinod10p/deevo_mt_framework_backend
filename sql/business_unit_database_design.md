# Business Units: Database Design and Migration to deevo_app_dev3

Nov 25, 2026 · @vinod · Status: **built on `deevo_app_dev3` (backend)** — updated Nov 27, 2026

A tenant (one company, e.g. *London Jeweler*) can now have many **business units** (its stores, warehouse, workshop, online shop). The tenant stays the isolation boundary between companies; the business unit labels and filters data *inside* a company. This document covers the design, every table change, and the plan to build a new database `deevo_app_dev3` and copy the data from `deevo_app_dev2`.

Related: [`rbac_database_design.md`](rbac_database_design.md) (roles and permissions), [`../docs/architecture.md`](../docs/architecture.md) (one schema per module), [`../prompts/tenant/BUSINESS_UNIT_BACKEND_PROMPT.md`](../prompts/tenant/BUSINESS_UNIT_BACKEND_PROMPT.md) (login and store-switch decisions, steps 0–9), [`../prompts/tenant/BUSINESS_UNIT_FRONTEND_PROMPT.md`](../prompts/tenant/BUSINESS_UNIT_FRONTEND_PROMPT.md) (React contract).

## 0. Status (Nov 27, 2026)

| Area | State |
|---|---|
| `deevo_app_dev3` | Built and loaded; the backend's `.env` points at it. `deevo_app_dev2` is untouched (rollback) |
| Database scripts | `dev3_10` default units, `dev3_11` report procedures, `dev3_12` custom roles moved to stores, `dev3_13` integrity triggers (§8) |
| Backend (branch `dev/bu`) | Login with a typed store, store switch, store re-check on refresh, store-aware permissions, `/auth/me` store fields, role assignment at a store (§7) |
| Tests on dev3 | Integration suite: 166 passed, 0 failed; the only skips are 8 saved-view tests that need an empty saved-view table |
| Not built yet | `TenantBUMixin` read filter, business unit admin API, `max_business_units` enforcement, store filters on reports, store-owned (inventory) tables, `email` / `crm` / `flow` / `wf` schemas in dev3 (§9) |

Where the build differs from the Nov 25 draft, the sections below say so and D10–D15 record why.

---

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Every tenant-data table carries `tenant_id` **and** `business_unit_id`, both `NOT NULL` | One rule everywhere; one mixin; per-store variations later need no schema change |
| D2 | **No `NULL` business unit.** Each tenant has one **root** unit (`bu_type = 'root'`) that owns tenant-wide data | `NULL` was ambiguous ("all stores" or "forgot to set it") and needs `OR IS NULL` everywhere |
| D3 | The root unit's name defaults to the tenant's name; code defaults to `COMPANY`. Logic checks **only `bu_type`**, never code or name | Tenants can rename freely; `tenant`, `hq` and `main` were rejected as names that clash with existing meanings |
| D4 | Every tenant gets root **plus a first store `MAIN`** at onboarding, even single-store tenants | Sales and stock always sit at a store; opening a second store needs no data migration |
| D5 | Only `store`-type units (and later `warehouse`, `online`) hold transactions and stock. Root never does | Keeps root as "the company", not a fake shop |
| D6 | A row is visible in a unit if it belongs to **that unit or an ancestor**. For overrides, the **nearest unit wins** | Shared data at root is seen by every store; a store can override a default |
| D7 | Staff access is per unit through `auth.user_role`. A role at root = all stores, including future ones | Staff can work across stores; owners need no change when a store opens |
| D8 | Stock is tracked per store. A transfer is two documents: transfer-out at the sender, transfer-in at the receiver | Every store-owned table keeps the plain `business_unit_id = @bu` filter |
| D9 | Platform rows keep `tenant_id = NULL` (and `business_unit_id = NULL`) where the table already mixes platform and tenant rows, guarded by existing checks (`scope_type` on report tables, `CK_role_platform_is_system` on `role`) | This `NULL` means "belongs to the platform", a separate concept from stores (see open item O1) |
| D10 | Staff **type the store code at login** (Company, Store, Email, Password — no dropdown, no lookup). It is required for staff on every client, checked after the password, matched trimmed and case-insensitive. Portal users sit at root; system users have no unit | Same model as the typed Company field; the app remembers the last store per device. A wrong store is not a password guess (no lockout) |
| D11 | Every store failure is one answer: `401` "You don't have access to this store" (unknown, closed, other tenant's, or not allowed); a missing store is "Store is required" | Does not reveal which stores exist |
| D12 | A member with **no roles** may use only their default store, else the active store coded `MAIN` — the one place logic reads a code (exception to D3, agreed Nov 26, 2026) | Keeps today's "member logs in with no permissions" behaviour |
| D13 | The session row is the source of truth for the current unit. The token's `business_unit_id` claim is informational. Switching store issues a new access **and** refresh token; refresh re-checks the store and ends the session if it is closed or no longer allowed | The server never trusts a client-supplied unit |
| D14 | A custom role assigned without a store goes to the user's **default store**; the root is reserved for tenant-wide roles (only platform `tenant_admin` today) | Today's Role Admin screen keeps working, and "all stores" stays reserved for roles meant for it |
| D15 | Migrated custom-role assignments moved from root to the member's default store (`dev3_12`, option B of open item Q1) | A new store must not silently inherit old "all stores" access |

---

## 2. At a glance

```
tenant.tenant  (London Jeweler)
└── business_unit  ROOT  "London Jeweler"     ← customers, products, roles, settings (defaults)
    ├── business_unit  STORE  KNIGHTSBRIDGE   ← sales, stock, cash, repairs; setting overrides
    ├── business_unit  STORE  MAYFAIR
    └── business_unit  WAREHOUSE  WH1

Visible at MAYFAIR  =  rows of MAYFAIR  +  rows of ROOT
Single-store tenant =  ROOT + MAIN (store picker hidden)
```

---

## 3. New table: `tenant.business_unit`

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `varchar(26)` | no | ULID, PK |
| `tenant_id` | `varchar(26)` | no | FK `tenant.tenant` |
| `parent_id` | `varchar(26)` | yes | `NULL` only for root (see check). FK `(parent_id, tenant_id)` → `business_unit (id, tenant_id)` |
| `bu_type` | `varchar(20)` | no | `root`, `store`, `warehouse`, `workshop`, `online` |
| `code` | `varchar(30)` | no | e.g. `COMPANY`, `MAIN`, `KNIGHTSBRIDGE`; editable |
| `name` | `nvarchar(255)` | no | Shown to users |
| `address_line1`, `address_line2`, `city`, `state`, `postal_code`, `country` | as `tenant.tenant` | yes | Store address (receipts, tax) |
| `timezone` | `varchar(50)` | yes | `NULL` → use tenant timezone |
| `currency` | `char(3)` | yes | `NULL` → use tenant currency |
| `sort_order` | `int` | no | Default 0 |
| standard columns | | | `is_active`, `is_deleted`, `deleted_at`, `deleted_by`, `row_version`, `created_at/by`, `updated_at/by` |

> `parent_id` is the one nullable key, and only on this table: it is the tree's top. Every *other* table references a unit with `NOT NULL`.

**Constraints and indexes**

| Name | Rule |
|---|---|
| `PK_business_unit` | `id` |
| `UQ_business_unit_id_tenant` | `UNIQUE (id, tenant_id)` — composite FK target for every other table |
| `UQ_business_unit_tenant_code` | `(tenant_id, code) WHERE is_deleted = 0` |
| `UQ_business_unit_root` | `(tenant_id) WHERE bu_type = 'root' AND is_deleted = 0` — exactly one root per tenant |
| `CK_business_unit_bu_type` | allowed values above |
| `CK_business_unit_root_parent` | `(bu_type = 'root' AND parent_id IS NULL) OR (bu_type <> 'root' AND parent_id IS NOT NULL)` |
| `CK_business_unit_deleted` | `deleted_at`/`deleted_by` set when `is_deleted = 1` |
| `CK_business_unit_country`, `CK_business_unit_currency` | code formats (added in dev3) |
| `IX_business_unit_tenant_sort` | `(tenant_id, sort_order)` — store lists and "first store" lookups |
| `FK_business_unit_parent` | `(parent_id, tenant_id)` → `(id, tenant_id)` — parent is always in the same tenant |

Root cannot be soft-deleted: to be enforced by the business unit admin API, which is not built yet (no code path deletes units today).

**Model:** `mtf/tenant/models/business_unit.py` (`BusinessUnit`, `BU_TYPE_ROOT`, `BU_TYPE_STORE`). Onboarding (`TenantService.create_tenant`) creates the root (`COMPANY`, `sort_order` 0) and `MAIN` (`sort_order` 1) in the same transaction (`mtf/tenant/business_units.py`).

**Levels:** start with two (root → units). `parent_id` allows regions later (root → region → store); the visibility lookup then needs the ancestor list (see open item O2).

---

## 4. Rules every table follows

1. **Both columns.** Tenant tables have `tenant_id NOT NULL` and `business_unit_id NOT NULL`.
2. **Same-tenant FK.** `FK_<table>_business_unit` is `(business_unit_id, tenant_id)` → `tenant.business_unit (id, tenant_id)`. Keep the separate `FK_<table>_tenant_id` too.
3. **Each table is declared `shared` or `owned`** (one class attribute on the SQLAlchemy model):

   | Kind | Typical rows at | Read filter (applied by the repository, never by hand) |
   |---|---|---|
   | `shared` (customers, products, roles, settings) | root, sometimes a store override | `business_unit_id IN (@bu, @root)` (later: `IN (ancestors of @bu)`) |
   | `owned` (sales, stock, cash, transfers) | a store | `business_unit_id = @bu` |

4. **Overrides:** when a shared table has the same key at root and at the current unit, the current unit's row wins. One helper resolves this; queries don't.
5. **Uniqueness:** tenant-wide codes stay `UNIQUE (tenant_id, code) WHERE is_deleted = 0` — *without* `business_unit_id`, so two stores can't create the same SKU. Override tables use `(tenant_id, business_unit_id, key)`. Store documents may be numbered per store: `(tenant_id, business_unit_id, doc_no)`.
6. **Indexes** lead with `(tenant_id, business_unit_id, …)`.
7. **Writes:**
   - Shared master data (customers, products) is created at root by any user allowed to create it. If you need "which store added this customer", add `created_bu_id`; never use `business_unit_id` for that.
   - Root rows of configuration tables (settings, role grants) are edited only by users with a root role. Store managers edit their own store's override.
   - Owned rows can only be written at a unit whose `bu_type` accepts transactions — never at root.
8. **"All stores" mode** (session unit = root) is read-only for owned tables.

---

## 5. Changes per table

### 5.1 Tables that get `business_unit_id`

| Table | Kind | BU value after migration | Other changes |
|---|---|---|---|
| `tenant.tenant_setting` | shared | root | New `UQ_tenant_setting (tenant_id, business_unit_id, key) WHERE is_deleted = 0` (there is no unique key today). Add `deleted_at`, `deleted_by` |
| `tenant.tenant_account` (customers) | shared | root | `UQ_tenant_account_code` stays `(tenant_id, account_code)`. Add `deleted_at` |
| `tenant.tenant_account_address` | shared | root (same as its account) | Add `deleted_at` |
| `auth.tenant_user` (staff membership) | shared | root | Add `default_business_unit_id` (FK, unit picked at login). Add `deleted_at`. Drop `invite_token` (see 5.3) |
| `auth.tenant_account_user` (portal membership) | shared | root | Add `deleted_at` |
| `auth.role` — tenant rows | shared | root | Add `is_tenant_wide bit NOT NULL DEFAULT 0`: only these roles may be assigned at root. Platform rows keep `tenant_id`/`business_unit_id` `NULL` (D9). Only platform `tenant_admin` is tenant-wide; tenants cannot set the flag yet |
| `auth.user_role` | shared | root at migration; then custom roles moved to the default store (`dev3_12`, D15) | `UQ_user_role` is `(tenant_id, user_id, account_id, business_unit_id, role_id) WHERE is_deleted = 0`, so one role can be held at two stores. Root only for `is_tenant_wide` roles (service rule, D14). Portal rows stay at root |
| `auth.role_report` | shared | root | `UQ_role_report` gains `business_unit_id` |
| `auth.session` | — (current context) | **not copied** (users sign in again) | `business_unit_id` = the store typed at login (D10) or switched to; root for portal sessions; `NULL` for system sessions (`CK_session_tenant_bu`). Add `deleted_at` |
| `txn.screen_field_config` | shared | root | `UQ_screen_field_config_tenant_id_field_id` gains `business_unit_id` (store overrides later) |
| `txn.screen_permission` | shared | root | `UQ_screen_permission_tenant_id_user_id_screen_id` gains `business_unit_id`. Per-user grants overlap with RBAC — check whether still used |
| `rpt.report_saved_view` — tenant rows | shared | root | Add `deleted_at`. System rows stay `NULL` (D9) |
| `rpt.report_definition` — tenant rows | shared | root | Add `deleted_at`. System rows stay `NULL` (D9) |
| `audit.audit_log` | log | the acting session's unit; root when none | `NULL` only when `tenant_id` is `NULL` (platform actions, `CK_audit_log_tenant_bu`). Add `IX_audit_log_tenant_bu (tenant_id, business_unit_id, created_at)`. `login` rows also record `new_values.business_unit_id`. `CK_audit_log_action` has no switch action, so a store switch is `action = 'update'` on `auth.session` with `new_values.event = 'business_unit_switch'` and the old / new unit |

### 5.2 Tables that do **not** get `business_unit_id`

| Table | Why |
|---|---|
| `tenant.tenant` | It *is* the tenant. Gains `max_business_units int NOT NULL DEFAULT 1` (stores only, root not counted) and `deleted_at` |
| `auth.app_user` | Global login identity, not tenant data |
| `auth.permission`, `auth.role_permission`, `auth.default_role_report` | Platform catalog / grants. `role_permission` of a tenant role inherits from its role |
| Definition child tables: `rpt.report_column`, `rpt.report_criteria`, `rpt.report_action`, `rpt.report_action_param`, `txn.screen`, `txn.screen_section`, `txn.screen_field`, `txn.lookup`, `txn.lookup_column`, `nav.menu_module`, `nav.screen`, `nav.menu_item` | Platform metadata; tenant-owned children inherit tenancy from the parent (see open item O3) |

### 5.3 Cleanups done in the same rebuild

| Change | Table(s) | Reason |
|---|---|---|
| Add `deleted_at datetime2(3) NULL` + `CK_<table>_deleted` | `app_user`, `session`, `tenant_user`, `tenant_account_user`, `tenant`, `tenant_account`, `tenant_account_address`, `tenant_setting`, `report_definition`, `report_column`, `report_criteria`, `report_saved_view` | Standard soft-delete columns; v1 tables lack them |
| `UQ_app_user_email_normalized (email_normalized) WHERE is_deleted = 0` | `auth.app_user` | Today nothing stops `A@x.com` and `a@x.com` both existing; login lookup scans the table |
| `UQ_app_user_external (auth_provider, external_id) WHERE external_id IS NOT NULL AND is_deleted = 0` | `auth.app_user` | One SSO identity → one user |
| `CK_app_user_auth_provider` | `auth.app_user` | Stop `Google` vs `google`. Values to confirm |
| Drop `invite_token` (plain text) | `auth.tenant_user` | `invite_token_hash` already exists; a plain-text token is a security risk. ✅ Dropped in dev3 and removed from `mtf/auth/models/tenant_user.py` |
| Drop table `rpt.report_permission` | — | Replaced by `auth.role_report`; no Python model uses it |
| **Keep** `role` on `tenant_user` / `tenant_account_user` for now | — | Still read by `mtf/auth/api/session.py` and `mtf/tenant/api/tenant_account_portal.py`. Remove later with expand/contract |
| Move `row_version` to its usual position | `auth.app_user` | Cosmetic only |

---

## 6. Single-store tenants

Most tenants will have one store. They get the same two units (root + `MAIN`) and the same backend rules; the UI simply hides stores:

| Area | Behaviour with one active store |
|---|---|
| Login | Staff still type a store (D10); the app prefills the last one used on the device, so it is `MAIN` after the first login |
| "All stores" mode | Available only to root-role users (admins); the app hides the switcher |
| Roles | Custom roles land at the default store (`MAIN`) without choosing (D14); `tenant_admin` stays at root |
| Settings | Edited at root; "override for this store" hidden |
| Reports | No store column or filter |

Login, refresh, switch and `/auth/me` all return `multi_store: bool` (more than one active non-root unit) so the frontend knows what to hide. Opening a second store = inserting one row; existing data is already in the right place, and nobody gains access to it until a role is assigned there (D15).

---

## 7. Application changes (this repo)

✅ built on branch `dev/bu` · ⏳ not built yet

| Area | Change | State |
|---|---|---|
| `mtf/shared/model_columns.py` | Shared column helpers and mixins (`StandardColumnsMixin`, `business_unit_fk`, `Model.new(by=…)`, `mark_deleted`) used by every model touched | ✅ |
| `mtf/tenant/business_units.py` | `root_unit_id` (cached), `first_store_id`, `membership_units`, `create_default_units` | ✅ |
| Every tenant insert | Writes `business_unit_id`: the root for tenant-wide rows, the session's unit for `session` and `audit_log` | ✅ |
| `mtf/tenant/services/business_unit_service.py` | `BusinessUnitService`: which units a staff user may use (D7, D12), `resolve_login_unit`, `recheck_session_unit`, `list_open_to_staff`, `is_multi_store`, `default_store_id`; one `StoreAccessError` (D11) | ✅ |
| `mtf/shared/security.py` | Access token gains a `business_unit_id` claim (informational, D13). No root-id claim | ✅ |
| `mtf/shared/deps.py` | `CurrentUser.business_unit_id`, read from the session row in the same query `get_current_user` already runs; `get_business_unit_id` dependency (401 when missing) | ✅ |
| `mtf/auth/services/session_service.py`, `mtf/auth/api/session.py` | Login requires `business_unit_code` for staff (D10, D11); refresh re-checks the store (D13); `POST /auth/session/business-unit` and `/auth/browser/session/business-unit` switch store; refresh and switch share one token rotation | ✅ |
| `mtf/auth/services/permission_resolver.py` | Effective roles = roles held at a root unit + roles held at the session's unit (joined to `tenant.business_unit`, no extra lookup); the unit is part of the cache key | ✅ |
| `GET /auth/me` | `business_unit`, `multi_store`, `business_units` (the units the user may switch to) | ✅ |
| `POST/DELETE /tenant/users/{id}/roles` | Optional `business_unit_id`; root only for tenant-wide roles (`409 AUTH_ROLE_CONFLICT`); unknown unit `404`; revoke at one store with `?business_unit_id=` (D14) | ✅ |
| `mtf/audit` | Writes `business_unit_id`; store switch audited as `update` + event (§5.1) | ✅ |
| `mtf/shared/database.py` | `TenantBUMixin` with `__bu_kind__ = "shared" \| "owned"`; base repository applies the read filter (§4.3) and stamps `tenant_id`/`business_unit_id` on insert | ⏳ |
| `mtf/tenant` business unit admin | API to list / create / rename / deactivate units; root cannot be deleted; enforce `max_business_units` | ⏳ |
| `mtf/rpt` | Store filter on reports; "All stores" only for root-role users | ⏳ |
| Role Admin | Let tenants mark custom roles tenant-wide (`is_tenant_wide` on role create / update) | ⏳ (not decided) |
| Tests | Unit tests for every rule above; live dev3 tests: `tests/auth/test_login_store_integration.py`, `test_store_permissions_integration.py`, `test_store_switch_integration.py`, `test_store_role_assignment_integration.py`, `tests/tenant/test_business_unit_service_integration.py`; shared helpers `tests/staff_login.py`, `tests/business_unit_fixtures.py` | ✅ |

**Tasks for other repos** (not done here):
- **Inventory** (`inventory.*`): stock tables owned per store; transfer-out / transfer-in documents; serialised items carry `current_bu_id`.
- **Email** (`email.mailbox`, `email.mailbox_credential`): add `business_unit_id` (root, or a store's own mailbox).
- **Frontend** (`deevoflow_react`): contract written in [`BUSINESS_UNIT_FRONTEND_PROMPT.md`](../prompts/tenant/BUSINESS_UNIT_FRONTEND_PROMPT.md) — typed Store field remembered per device, header switcher, store-aware role assignment. `deevo_admin`: business unit admin screen once the API exists.

---

## 8. Migration: `deevo_app_dev2` → `deevo_app_dev3`

`deevo_app_dev2` stays untouched and is the rollback. Steps 0–5 are done; the scripts that ran on dev3 after the table rebuild are listed in Step 4b.

### Step 0 — confirm what dev2 really looks like
The repo has base scripts plus fix scripts (`rbac_fix_01`–`05`, `nav_menu_fix_01`), so it may not match dev2 exactly. Export dev2's real definitions (`sys.columns`, `sys.indexes`, `sys.foreign_keys`, `sys.check_constraints`) and compare with the scripts. Resolve differences before writing the dev3 DDL.

### Step 1 — pre-migration checks on dev2 (must return no rows)
- Duplicate live emails: `email_normalized` with `COUNT(*) > 1 WHERE is_deleted = 0`.
- Duplicate SSO identities: `(auth_provider, external_id)` duplicates.
- Duplicate settings: `(tenant_id, key)` duplicates in `tenant_setting`.
- Orphans: rows whose `tenant_id` has no `tenant.tenant` row.
- Soft-deleted rows with no `deleted_by` (decide a fallback, e.g. the system user `01HYSTEM00000000000000000`).

### Step 2 — create dev3 from clean scripts
One consolidated script per schema, reflecting the **final** state (no fix scripts), run as the DDL login:

| Order | Script (new) | Contents |
|---|---|---|
| 1 | `dev3_00_database.sql` | Database, schemas (`auth`, `tenant`, `audit`, `rpt`, `txn`, `nav`, `email`), logins/grants |
| 2 | `dev3_01_tenant.sql` | `tenant`, `business_unit`, `tenant_account`, `tenant_account_address`, `tenant_setting` |
| 3 | `dev3_02_auth.sql` | `app_user`, `session`, `tenant_user`, `tenant_account_user`, RBAC tables |
| 4 | `dev3_03_rpt_txn_nav.sql` | report, screen and menu tables (without `rpt.report_permission`) |
| 5 | `dev3_04_audit.sql` | `audit_log` + its UPDATE/DELETE deny |

Foreign keys that point at `auth.app_user` from tenant tables create a cycle with `created_by`; create tables first, load data, **then** add FKs and checks `WITH CHECK` (step 4).

### Step 3 — copy data
Run as one script per schema, in FK order, with `SET IDENTITY_INSERT` not needed (ULIDs). `row_version` is regenerated automatically.

1. **Copy platform data as is:** `app_user`, `permission`, platform `role` rows, `role_permission`, `default_role_report`, platform report / screen / menu definitions.
2. **Copy tenants**, then **create business units** for each tenant:
   - root: new ULID, `bu_type = 'root'`, `code = 'COMPANY'`, `name = tenant.name`, address/timezone copied from the tenant;
   - store: new ULID, `bu_type = 'store'`, `code = 'MAIN'`, `name = 'Main store'`, `parent_id = root`.
   **As built:** [`dev3_10_business_unit_defaults.sql`](dev3_10_business_unit_defaults.sql) uses deterministic ids instead of a mapping table — `ROOT = LEFT('01JBXR' + hex(SHA2_256(N'bu-root|' + tenant_id)), 26)`, `MAIN` the same with `'01JBXM'` / `bu-main|` — so any later script can compute a tenant's units without a lookup. Units are created for soft-deleted tenants too.
3. **Copy tenant tables** joining `migration.tenant_bu_map`:
   - shared tables → `business_unit_id = root_bu_id`;
   - `tenant_user.default_business_unit_id = main_bu_id`;
   - active `auth.session` rows → **not copied** (users sign in again on dev3); keep history only if needed;
   - `audit_log` → `business_unit_id = root_bu_id` where `tenant_id` is set, else `NULL`.
4. **Fill `deleted_at`** for rows with `is_deleted = 1`: use `updated_at` (best available value).
5. **Mark tenant-wide roles:** `is_tenant_wide = 1` on platform `tenant_admin` only (the owner role no longer exists since `rbac_fix_05`).

### Step 4 — constraints and validation
- Add FKs, checks and unique indexes `WITH CHECK` — any failure means bad data, fix and rerun.
- Row counts: every table in dev3 = dev2 (minus `session` and `rpt.report_permission`).
- Each tenant has exactly one root and one `MAIN`.
- No `business_unit_id` points at another tenant's unit (guaranteed by the composite FK).
- Spot-check: log in as a tenant admin, a portal user and a system admin; run a report; open a screen.

### Step 4b — scripts applied to dev3 after the rebuild

| Script | What it does | Result on dev3 |
|---|---|---|
| [`dev3_11_rpt_procedures.sql`](dev3_11_rpt_procedures.sql) | Copies the 38 `rpt.usp_*` procedures and `rpt.TR_report_definition_scope_guard` from dev2 (`CREATE OR ALTER`) | All compile; the CRM ones fail at run time until the `crm` schema is migrated |
| [`dev3_12_move_custom_roles_to_store.sql`](dev3_12_move_custom_roles_to_store.sql) | Moves live staff assignments of non-tenant-wide roles from root to the member's default store, else `MAIN`; logs each change in `auth.user_role_store_move_log` (undo SQL in the file) | 30 moved, 0 retired, 0 left at root; portal and `tenant_admin` rows untouched |
| [`dev3_13_integrity_triggers.sql`](dev3_13_integrity_triggers.sql) | Copies `auth.TR_user_role_integrity`, `TR_role_report_integrity`, `TR_default_role_report_integrity`, `TR_role_tenant_immutable`, `tenant.TR_tenant_setting_rbac_screens_one_way` | All five live; no business-unit change needed (the composite FK keeps each row's unit in its tenant) |

Not copied yet: the eight `email.*` `updated_at` triggers (with the email migration).

### Step 5 — switch the app
✅ Done. The backend's `.env` points at `deevo_app_dev3`; the integration suite passes there (166 passed, 0 failed). Tests that re-apply old dev2 scripts (`rbac_fix_*`, seeds, backfill) are excluded from dev3 runs. Keep dev2 read-only until dev3 is accepted.

---

## 9. Open items

| # | Question | State |
|---|---|---|
| O1 | Platform rows use `tenant_id = NULL` in `role`, `report_definition`, `report_saved_view`, `audit_log`. Keep, or split platform rows into separate tables? | Kept (D9) |
| O2 | Two levels only (root → stores) or regions from day one? | Two levels now; `parent_id` is ready for regions |
| O3 | Should definition child tables (`report_column`, `screen_field`, …) get `tenant_id` + `business_unit_id` too? | Decide with row-level security plans; not needed for the first cut |
| O4 | Can store managers create store-only products or customers? | Not at first; shared master data lives at root |
| O5 | Is "All stores" mode read-only? | ✅ Yes for owned tables — to be enforced with the first store-owned table |
| O6 | Which roles are `is_tenant_wide`? | ✅ Platform `tenant_admin` only. Open: should tenants be able to mark custom roles tenant-wide? (prompt Q4) |
| O7 | Allowed `auth_provider` values | `local`, `google`, `microsoft` — confirm |
| O8 | When do `tenant_user.role` / `tenant_account_user.role` go? | After `session.py` and `tenant_account_portal.py` read roles from `user_role` |
| O9 | Migrated custom-role assignments held at root (prompt Q1) | ✅ Moved to the member's default store (D15, `dev3_12`) |
| O10 | "All stores" at login or only through the switcher (prompt Q2) | ✅ Both, for root-role users |
| O11 | Token claim name (prompt Q3) | ✅ `business_unit_id` |
| O12 | Schemas not yet in dev3: `email`, `crm`, `flow`, `wf`, six DeevoFlow `auth.*` tables, and the eight `email.*` triggers | Migrate later; mailbox endpoints and CRM reports fail on dev3 until then |
