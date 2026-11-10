# Roles and Permissions: Database Design

Nov 8, 2026 · @vinod

Six tables in the `auth` schema decide what each user can do on screens and reports: users get roles, roles bundle permissions, and anything not granted is denied. The script is [`auth_rbac_schema_v3.sql`](auth_rbac_schema_v3.sql); it builds on the existing `app_user`, `tenant_user` and `tenant_account_user` tables and replaces the unused `rpt.report_permission`. Coding order: [`rbac_development_steps.md`](rbac_development_steps.md). Remaining review items after step 10: [`rbac_review_fixes.md`](rbac_review_fixes.md).

## At a glance

Arrows point from a table to the table it references; the dashed arrow means "copied".

```
                 ┌──────────────────┐        ┌──────────────────────┐        ┌─────────────────────────┐
                 │ app_user         │◄───────│ user_role            │───────►│ tenant · tenant_account │
                 │ identity,        │        │ who holds which      │        │ where an assignment     │
                 │ user_scope       │        │ role, where          │        │ applies                 │
                 └──────────────────┘        └──────────┬───────────┘        └─────────────────────────┘
                          ▲                             │
                          │                             ▼
┌─────────────────────────┴───────┐          ┌──────────────────────┐        ┌─────────────────────────┐
│ Membership                      │          │ role                 │◄───────│ role_report             │
│ tenant_user,                    │          │ tenant role or       │        │ report access per role  │
│ tenant_account_user             │          │ platform template    │        │ can_view, can_export    │
│ must be active for access       │          └──────────────────────┘        └─────────────────────────┘
└─────────────────────────────────┘                     ▲                                ▲
                                                        │                                ┊ copied at onboarding
                                             ┌──────────┴───────────┐        ┌───────────┴─────────────┐
                                             │ role_permission      │        │ default_role_report     │
                                             │ permissions in       │        │ platform default grants │
                                             │ each role            │        │ never read at runtime   │
                                             └──────────┬───────────┘        └─────────────────────────┘
                                                        │
                                                        ▼
                                             ┌──────────────────────┐
                                             │ permission           │
                                             │ catalog, e.g.        │
                                             │ screen.customer.view │
                                             └──────────────────────┘
```

A user's roles live in `user_role`, scoped to a tenant or account; each role grants catalog permissions through `role_permission` and report access through `role_report`, which each tenant receives as a copy of the platform defaults in `default_role_report`.

## The tables

Each table has one job; the platform owns the permission catalog and default grants, while tenants own their roles, assignments and report grants.

| Table | Purpose | Key columns | Defined by |
| --- | --- | --- | --- |
| `auth.permission` | Catalog of every action that can be granted | `code` (unique), `resource_type`, `resource_code`, `action`, `user_scope` | Platform, seeded with each release |
| `auth.role` | A named bundle of permissions | `tenant_id` (NULL = platform role, always `is_system = 1`), `code`, `name`, `user_scope`, `is_system` | Platform templates and tenant custom roles |
| `auth.role_permission` | Which permissions a role grants | `role_id`, `permission_id`, `user_scope` | Whoever owns the role |
| `auth.user_role` | Which roles a user holds, and where | `tenant_id`, `user_id`, `account_id`, `role_id`, `user_scope` | Tenant admin (system admin for system users) |
| `auth.role_report` | Report access by role, owned by a tenant | `tenant_id` (required), `role_id`, `report_id`, `can_view`, `can_export` | Tenant admin, per report |
| `auth.default_role_report` | Platform default report grants, copied to each new tenant | `role_id`, `report_id`, `can_view`, `can_export` | Platform |

**Permission codes** follow `<resource_type>.<resource_code>.<action>`, for example `screen.customer.update`. Allowed values:

- `resource_type`: `menu`, `screen`, `api` (`menu` is ready for the dynamic menu later)
- `action`: `view`, `create`, `update`, `delete`, `export`, `import`, `approve`
- `user_scope`: `system`, `tenant`, `tenant_account`, matching `app_user.user_scope`

**Standard columns** on every table: `is_active`, soft delete (`is_deleted`, `deleted_at`, `deleted_by`), `row_version` for optimistic concurrency, and `created_at/by`, `updated_at/by` with foreign keys to `app_user`. Nothing is hard-deleted. A `CK_<table>_deleted` check on each table requires `deleted_at` and `deleted_by` whenever `is_deleted = 1`.

**Key indexes**

| Index | Enforces or speeds up |
| --- | --- |
| `UQ_permission_code` | Permission code unique among live rows |
| `UQ_role_tenant_code` | Role code unique within a tenant; two tenants can both have `support_agent` |
| `UQ_role_platform_code` | Platform role codes unique across the platform |
| `UQ_role_permission` | A permission granted once per role; can be re-granted after removal |
| `UQ_user_role` | Same role never assigned twice in the same place; leads with `tenant_id`, so it also serves the login lookup and listing a tenant's assignments |
| `IX_user_role_role_id` | "Who holds this role?" and the FK check when a role is removed |
| `UQ_role_report` | One grant per tenant, role and report |
| `UQ_default_role_report` | One default grant per role and report |

All unique indexes skip soft-deleted rows, so a deleted code, grant or assignment can be created again.

**Constraint names** follow `PK_`, `UQ_`, `FK_<table>_<column>`, `CK_<table>_<rule>` and `DF_<table>_<column>`.

## Scope enforced by the database

A tenant user can never end up with a system permission, because SQL Server itself checks that scopes match.

- `role` and `permission` each carry a unique `(id, user_scope)` constraint, and step 0 of the script adds the same to `app_user`. These add no new rule; they exist only as foreign-key targets.
- `role_permission` stores `user_scope` and references `role(id, user_scope)` and `permission(id, user_scope)`, so a role can only grant permissions of its own scope.
- `user_role` stores `user_scope` and references `app_user(id, user_scope)` and `role(id, user_scope)`, so a user can only hold roles of their own scope.
- `CK_user_role_scope_shape` ties the place columns to the scope:

| user_scope | tenant_id | account_id |
| --- | --- | --- |
| system | NULL | NULL |
| tenant | required | NULL |
| tenant_account | required | required |

One consequence: once a role or permission is referenced, its `user_scope` can't change. That is intended.

## How access is decided

A user can do something only if they belong where they are working, and at least one of their roles there grants it.

1. **Membership.** The user must have an active membership row: `tenant_user` for tenant staff, `tenant_account_user` for account users. System users have no membership row; they resolve `user_role` where `tenant_id` and `account_id` are both NULL. System JWTs cannot call tenant endpoints in v1 (`require_scope("tenant")` already denies them). Deactivating a membership removes all access in that tenant at once, even if `user_role` rows remain.
2. **Roles in that place.** `user_role` is matched on the user plus the tenant (and account, for account users):

   | user_scope | tenant_id | account_id | Membership checked in |
   | --- | --- | --- | --- |
   | system | NULL | NULL | none |
   | tenant | set | NULL | `tenant_user` |
   | tenant_account | set | set | `tenant_account_user` |

3. **Grants only.** Effective permissions are everything any of the user's roles grants, combined. There are no deny rules: if no role grants it, the user can't do it.

The permission set is loaded **per request** and memoized on that request only (not for the session). Three `require_permission` calls in one request share one query. Tenant users:

```sql
SELECT DISTINCT p.code
FROM auth.tenant_user tu
JOIN auth.user_role ur       ON ur.user_id = tu.user_id AND ur.tenant_id = tu.tenant_id
JOIN auth.role r             ON r.id = ur.role_id
JOIN auth.role_permission rp ON rp.role_id = r.id
JOIN auth.permission p       ON p.id = rp.permission_id
WHERE tu.user_id   = @user_id
  AND tu.tenant_id = @tenant_id
  AND tu.is_active = 1 AND tu.is_deleted = 0
  AND ur.account_id IS NULL
  AND ur.is_active = 1 AND ur.is_deleted = 0
  AND r.is_active  = 1 AND r.is_deleted  = 0
  AND p.is_active  = 1 AND p.is_deleted  = 0;
```

For account users, join `tenant_account_user` instead and match `ur.account_id` to its `account_id`. System users have no membership join:

```sql
SELECT DISTINCT p.code
FROM auth.user_role ur
JOIN auth.role r             ON r.id = ur.role_id
JOIN auth.role_permission rp ON rp.role_id = r.id
JOIN auth.permission p       ON p.id = rp.permission_id
WHERE ur.user_id    = @user_id
  AND ur.tenant_id  IS NULL
  AND ur.account_id IS NULL
  AND ur.is_active  = 1 AND ur.is_deleted = 0
  AND r.is_active   = 1 AND r.is_deleted  = 0
  AND p.is_active   = 1 AND p.is_deleted  = 0;
```

## Screens

Each data entry screen gets one permission per action, and the backend checks it on every request. Example for a Customer screen:

| Permission code | Allows | Backend check |
| --- | --- | --- |
| `screen.customer.view` | Open the screen, list and read records | `GET /customers`, `GET /customers/{id}` |
| `screen.customer.create` | Add a record | `POST /customers` |
| `screen.customer.update` | Edit a record | `PUT /customers/{id}` |
| `screen.customer.delete` | Remove a record | `DELETE /customers/{id}` |
| `screen.customer.export` | Download the list | `GET /customers/export` |

- **Backend:** every endpoint requires its permission. This is the check that protects the data.
- **Frontend:** buttons and links the user can't use are hidden, using the same permission set. This is a convenience only.
- **Navigation for now:** until the dynamic menu is built, the hard-coded menu hides a link when the user lacks that screen's `view` permission.

## Reports

Reports are rows in `rpt.report_definition`, so access is granted per report and per role in `role_report`, not through permission codes. Every `role_report` row belongs to a tenant. Example:

| Role | Report | can_view | can_export |
| --- | --- | --- | --- |
| Support Team Lead | Monthly Ticket Summary | yes | yes |
| Support Agent | Monthly Ticket Summary | yes | no |
| Support Team Lead | Agent Performance | yes | no |

A user sees a report if any of their roles has `can_view`, and can export it if any has `can_export`; `can_export` requires `can_view`. When a tenant creates a report, the admin picks which roles can see it. This replaces the per-user `rpt.report_permission`, which the script drops.

The catalog omits reports the caller cannot view. GET-by-id and `/run` for a hidden or unknown report return **404**, not 403, so a user cannot tell that a report exists.

**Platform default grants** are copied, not shared. The platform keeps its defaults in `default_role_report`, which is never read at runtime:

1. **Onboarding:** when a tenant is created, its rows are copied into `role_report` with the new `tenant_id`.
2. **Ownership:** from then on the tenant owns those rows and can change or remove any of them, defaults included.
3. **New defaults later:** existing tenants don't get them automatically. An explicit "apply to all tenants" script inserts only the missing rows, so rolling out a change is a deliberate, recorded decision.
4. **Existing tenants (backfill):** before report enforcement goes live, a one-time idempotent backfill copies missing `default_role_report` rows into `role_report` and maps each live membership `role` string to `user_role`. The same script is the later "apply defaults to all tenants" tool.

This keeps every grant in one place per tenant, and avoids platform rows that a tenant could never remove under grants-only.

## Dual-write while membership.role is still master

Until RBAC owns the gates, `tenant_user.role` and `tenant_account_user.role` remain the source of truth. Every create/update/soft-delete of those columns also upserts or revokes `user_role` in the same transaction.

| Membership table | `role` value | Template `auth.role.code` |
| --- | --- | --- |
| `tenant_user` | `owner`, `admin` | `tenant_admin` |
| `tenant_user` | `member`, `viewer` | `tenant_member` |
| `tenant_account_user` | `admin` | `account_admin` |
| `tenant_account_user` | `member` | `account_member` |

If the template role is missing, the write fails. Do not silently skip.

## Rules the service layer enforces

The database guarantees structure; these rules need application logic and live in the role service.

| The database enforces | The service enforces |
| --- | --- |
| No duplicate permissions, roles, grants or assignments | A tenant assigns only its own roles or platform templates |
| Valid scope, resource type and action values | A `role_report` row's tenant matches its role's tenant (for tenant roles) |
| Every reference points to a real row | Admins can't grant permissions they don't hold |
| `user_scope` matches across user, role and permission (composite FKs) | Tenants can't edit roles with `is_system = 1` |
| Place columns match the scope (`CK_user_role_scope_shape`) | A tenant always keeps at least one active admin |
| Platform roles are always `is_system = 1`; system roles never belong to a tenant | The user has an active membership before a role is assigned |
| Soft-deleted rows record when and by whom | `default_role_report` uses only platform template roles and platform-wide reports |
| Concurrent edits don't overwrite each other | |

Every role change, permission change and assignment writes a row to `audit.audit_log`. Because `deleted_by` is required, automated deletes such as tenant offboarding need a service-account row in `app_user` to attribute them to.

## Deployment

Run [`auth_rbac_schema_v3.sql`](auth_rbac_schema_v3.sql) against `deevo_app_dev2`. It needs `auth.app_user`, `tenant.tenant`, `tenant.tenant_account` and `rpt.report_definition` to exist. Step 0 of the script adds a `UQ_app_user_id_user_scope` constraint to the existing `app_user` table; it can't fail on existing data because `id` is already unique. The script drops `rpt.report_permission` at the end; the `txn.screen_permission` drop is included but commented out.

Order (see [`rbac_development_steps.md`](rbac_development_steps.md)):

1. DDL: the six tables
2. Models
3. Resolver
4. Idempotent seed (fixed ULIDs)
5. Backfill existing tenants
6. Onboarding + dual-write on membership APIs
7. Report enforcement (end-to-end proof)
8. `GET /me`, then catalog and assignment CRUD
9. Later: `create_nav_menu.sql` and `menu.*` permissions

**Open items**

- [x] Platform-wide reports: `rpt.report_definition.scope_type = 'system'` with `tenant_id` NULL already exists. Keep `default_role_report`.
- [ ] Check `txn.screen_permission` for data and references, then enable its drop. Product screens already prefer RBAC via `require_screen_permission` (step 10); keep the table until no tenant still needs the fallback.
- [ ] Create a service-account row in `app_user` for automated deletes
- [ ] Drop `tenant_user.role` and `tenant_account_user.role` after dual-write is the only writer and RBAC owns the gates
- [ ] Add `deleted_at` to `tenant_user` and `tenant_account_user` for consistency
- [ ] List the current data entry screens for the seed script
