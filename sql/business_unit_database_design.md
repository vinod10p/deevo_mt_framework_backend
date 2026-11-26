# Business Units: Database Design and Migration to deevo_app_dev3

Nov 25, 2026 · @vinod · Status: draft for review

A tenant (one company, e.g. *London Jeweler*) can now have many **business units** (its stores, warehouse, workshop, online shop). The tenant stays the isolation boundary between companies; the business unit labels and filters data *inside* a company. This document covers the design, every table change, and the plan to build a new database `deevo_app_dev3` and copy the data from `deevo_app_dev2`.

Related: [`rbac_database_design.md`](rbac_database_design.md) (roles and permissions), [`../docs/architecture.md`](../docs/architecture.md) (one schema per module).

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
| `FK_business_unit_parent` | `(parent_id, tenant_id)` → `(id, tenant_id)` — parent is always in the same tenant |

Root cannot be soft-deleted (enforced in the service; optionally a trigger).

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
| `auth.role` — tenant rows | shared | root | Add `is_tenant_wide bit NOT NULL DEFAULT 0`: only these roles may be assigned at root. Platform rows keep `tenant_id`/`business_unit_id` `NULL` (D9) |
| `auth.user_role` | shared | root (all current assignments) | `UQ_user_role` becomes `(tenant_id, user_id, account_id, business_unit_id, role_id)`. Add `IX_user_role_bu (tenant_id, business_unit_id)`. Service rule: root assignment only for `is_tenant_wide` roles |
| `auth.role_report` | shared | root | `UQ_role_report` gains `business_unit_id` |
| `auth.session` | — (current context) | user's `MAIN` store, or root for root-role users with >1 store | `business_unit_id` = unit the user is working in; changes on store switch. Add `deleted_at` |
| `txn.screen_field_config` | shared | root | `UQ_screen_field_config_tenant_id_field_id` gains `business_unit_id` (store overrides later) |
| `txn.screen_permission` | shared | root | `UQ_screen_permission_tenant_id_user_id_screen_id` gains `business_unit_id`. Per-user grants overlap with RBAC — check whether still used |
| `rpt.report_saved_view` — tenant rows | shared | root | Add `deleted_at`. System rows stay `NULL` (D9) |
| `rpt.report_definition` — tenant rows | shared | root | Add `deleted_at`. System rows stay `NULL` (D9) |
| `audit.audit_log` | log | unit of the request; root when none | `NULL` only when `tenant_id` is `NULL` (platform actions). Add `IX_audit_log_tenant_bu (tenant_id, business_unit_id, created_at)` |

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
| Drop `invite_token` (plain text) | `auth.tenant_user` | `invite_token_hash` already exists; a plain-text token is a security risk. Model `mtf/auth/models/tenant_user.py` still maps it — remove there too |
| Drop table `rpt.report_permission` | — | Replaced by `auth.role_report`; no Python model uses it |
| **Keep** `role` on `tenant_user` / `tenant_account_user` for now | — | Still read by `mtf/auth/api/session.py` and `mtf/tenant/api/tenant_account_portal.py`. Remove later with expand/contract |
| Move `row_version` to its usual position | `auth.app_user` | Cosmetic only |

---

## 6. Single-store tenants

Most tenants will have one store. They get the same two units (root + `MAIN`) and the same backend rules; the UI simply hides stores:

| Area | Behaviour with one active store |
|---|---|
| Login | Session goes straight to `MAIN`; no picker |
| "All stores" mode | Not offered |
| Roles | Assigned at root; admins never choose a store |
| Settings | Edited at root; "override for this store" hidden |
| Reports | No store column or filter |

The current-user response includes `multi_store: bool` (more than one active non-root unit) so the frontend knows what to hide. Opening a second store = inserting one row; existing data is already in the right place.

---

## 7. Application changes (this repo)

| Area | Change |
|---|---|
| `mtf/shared/security.py` | Access token gains `business_unit_id` (and the root id) claims |
| `mtf/shared/deps.py` | `CurrentUser` gains `business_unit_id`, `root_business_unit_id`, `business_unit_ids` (units the user may access); `get_current_user` validates the session's unit on every request. New `get_business_unit_id` dependency |
| `mtf/shared/database.py` | `TenantBUMixin` with `__bu_kind__ = "shared" | "owned"`; base repository applies the read filter (§4.3) and stamps `tenant_id`/`business_unit_id` on insert |
| `mtf/tenant` | `business_unit` model, schemas, service, API (list, create, update, deactivate); onboarding creates root + `MAIN`; enforce `max_business_units` |
| `mtf/auth/api/session.py` | Choose unit at login (`tenant_user.default_business_unit_id`, else the only store, else picker); `POST /auth/session/business-unit` to switch; permissions recomputed for the new unit |
| `mtf/auth` RBAC | Effective permissions = roles at root + roles at the current unit; root assignment only for `is_tenant_wide` roles |
| `mtf/rpt` | Implicit filter on `business_unit_id` for the user's accessible units; "All stores" only for root-role users |
| `mtf/audit` | Write `business_unit_id` |
| Tests | Same tenant / other store; root role; store role; user with no role at the current store; single-store tenant; second store opened |

**Tasks for other repos** (not done here):
- **Inventory** (`inventory.*`): stock tables owned per store; transfer-out / transfer-in documents; serialised items carry `current_bu_id`.
- **Email** (`email.mailbox`, `email.mailbox_credential`): add `business_unit_id` (root, or a store's own mailbox).
- **Frontend** (`deevoflow_react`, `deevo_admin`): store picker and switcher, `multi_store` flag, business unit admin screen.

---

## 8. Migration: `deevo_app_dev2` → `deevo_app_dev3`

`deevo_app_dev2` stays untouched and is the rollback.

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
   ULIDs are generated by a small Python script (or a T-SQL ULID function) and stored in a mapping table `migration.tenant_bu_map (tenant_id, root_bu_id, main_bu_id)`.
3. **Copy tenant tables** joining `migration.tenant_bu_map`:
   - shared tables → `business_unit_id = root_bu_id`;
   - `tenant_user.default_business_unit_id = main_bu_id`;
   - active `auth.session` rows → **not copied** (users sign in again on dev3); keep history only if needed;
   - `audit_log` → `business_unit_id = root_bu_id` where `tenant_id` is set, else `NULL`.
4. **Fill `deleted_at`** for rows with `is_deleted = 1`: use `updated_at` (best available value).
5. **Mark tenant-wide roles:** set `is_tenant_wide = 1` on owner/admin roles (list to confirm).

### Step 4 — constraints and validation
- Add FKs, checks and unique indexes `WITH CHECK` — any failure means bad data, fix and rerun.
- Row counts: every table in dev3 = dev2 (minus `session` and `rpt.report_permission`).
- Each tenant has exactly one root and one `MAIN`.
- No `business_unit_id` points at another tenant's unit (guaranteed by the composite FK).
- Spot-check: log in as a tenant admin, a portal user and a system admin; run a report; open a screen.

### Step 5 — switch the app
Point the backend's connection settings at `deevo_app_dev3` (after the code in §7 is ready), run the full test suite including the live-database integration suite, then keep dev2 read-only until dev3 is accepted.

---

## 9. Open items

| # | Question | Recommendation |
|---|---|---|
| O1 | Platform rows use `tenant_id = NULL` in `role`, `report_definition`, `report_saved_view`, `audit_log`. Keep, or split platform rows into separate tables? | Keep (D9): separate concept from stores, already guarded by check constraints |
| O2 | Two levels only (root → stores) or regions from day one? | Two levels now; `parent_id` is ready for regions |
| O3 | Should definition child tables (`report_column`, `screen_field`, …) get `tenant_id` + `business_unit_id` too? | Decide with row-level security plans; not needed for the first cut |
| O4 | Can store managers create store-only products or customers? | Not at first; shared master data lives at root |
| O5 | Is "All stores" mode read-only? | Yes for owned tables |
| O6 | Which roles are `is_tenant_wide`? | Owner / tenant admin; confirm list |
| O7 | Allowed `auth_provider` values | `local`, `google`, `microsoft` — confirm |
| O8 | When do `tenant_user.role` / `tenant_account_user.role` go? | After `session.py` and `tenant_account_portal.py` read roles from `user_role` |
