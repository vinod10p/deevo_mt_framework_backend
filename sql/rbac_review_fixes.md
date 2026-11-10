# RBAC v3 — Review Fixes

Nov 9, 2026 · @vinod

Companion to [rbac_database_design.md](rbac_database_design.md) and [rbac_development_steps.md](rbac_development_steps.md). Steps 0–10 are done. Items **1 and 2** from the post-step-10 review are done (dual-write no longer deletes custom roles; deactivating a role runs the last-admin check). This file is the remaining code review (items 3–9). Do not start until CRM tenant testing is far enough along.

**Out of scope here:** item 10 (Lead behaviour for members vs portal), moving assignment routes to `require_permission`, the development-steps **Later** list (`menu.*`, drop membership.role, drop `txn.screen_permission`, service-account user).

## Status

| Item | What | Status |
| --- | --- | --- |
| 1 | Dual-write must not delete custom `user_role` rows | Done |
| 2 | Deactivating a role runs last-admin | Done |
| 3 | Last-admin ignores inactive memberships | Pending |
| 4 | Backfill copies `is_active`; stale template roles | Pending |
| 5 | Assigning a role checks that role’s report grants | Pending |
| 6 | Tenants can grant reports on portal template roles | Pending |
| 7 | First grant on a tenant-owned report | Pending |
| 8 | Export helpers (`screen` export + report `require_export`) | Pending |
| 9 | Report services fail closed without a user | Pending |
| — | Doc drift | Pending |

Assumptions below were chosen when the decision questions were skipped. Change them before coding if you want a different approach.

## Item 3: last-admin ignores inactive memberships

[`mtf/auth/services/rbac_assignment.py`](../mtf/auth/services/rbac_assignment.py) `_admin_assignment_stmt`: join `TenantUser` on `(user_id, tenant_id)` with `is_active = 1` and `is_deleted = 0`. The `UPDLOCK, HOLDLOCK` hint stays on `user_role`.

Test: compile the statement and assert it filters on active `tenant_user`.

## Item 4: backfill status and stale template roles

[`sql/auth_rbac_backfill_v3.sql`](auth_rbac_backfill_v3.sql):

- The `user_role` inserts copy `is_active` from `tenant_user` / `tenant_account_user`.
- New `UPDATE` makes existing template-role rows' `is_active` match the membership.
- **Assumption:** a `@actor varchar(26)` variable at the top. The script `THROW`s unless it is a live `app_user` with `user_scope = 'system'`. It is used to soft-delete template-role rows (`tenant_admin`, `tenant_member`, `account_admin`, `account_member`) that no longer match the membership string. Custom roles are never touched.

Tests:

- Update [`tests/auth/test_rbac_backfill.py`](../tests/auth/test_rbac_backfill.py) static checks.
- Extend [`tests/auth/test_rbac_backfill_integration.py`](../tests/auth/test_rbac_backfill_integration.py): idempotent re-run, plus an inactive member who ends up with an inactive `user_role`.

Re-apply the updated backfill on `deevo_app_dev2` (SSMS, with `@actor` set) before the live backfill test.

## Item 5: assigning a role checks report grants too

- New helper `report_grants_for_role(db, tenant_id, role_id)` in `rbac_assignment.py`.
- [`mtf/auth/services/user_role.py`](../mtf/auth/services/user_role.py) `create` calls `assert_report_escalation` for each live `role_report` row of that role, after the existing permission-code check.

Test: assigning a role that carries a report grant the actor lacks returns 403 `AUTH_ROLE_FORBIDDEN`.

## Item 6: tenants manage report grants for portal template roles

- New `report_grant_role_filter(tenant_id)` in `rbac_assignment.py`: tenant custom roles, plus platform templates with `user_scope` `tenant` or `tenant_account`. Never `system`.
- [`mtf/auth/services/role_report.py`](../mtf/auth/services/role_report.py) uses it instead of `require_assignable_role`.
- `user_role` assignment keeps the existing tenant-only filter.

Test: list and create a grant on `account_member`; `system_admin` is still 404.

## Item 7: tenant-owned reports can get their first grant

- **Assumption (exemption):** `assert_report_escalation` gets a `tenant_owned` flag. When the report belongs to the caller's tenant and the caller holds `api.auth.role.update`, the "you must hold it" check is skipped.
- Platform reports keep the full escalation rule.
- `RoleReportService.create` / `update` pass the flag, using the report row that `require_tenant_report` already returns.

Tests:

- An admin grants view on a tenant-owned report they don't hold, and it succeeds.
- The same grant on a platform report is still 403.

## Item 8: export checks for products to call (no export endpoint)

**Assumption:** add helpers only.

Screens, in [`mtf/txn/services/screen_permission.py`](../mtf/txn/services/screen_permission.py) and [`mtf/txn/services/screen_access.py`](../mtf/txn/services/screen_access.py):

- `ScreenOperation` gains `"export"`; `ScreenEffectivePermissions` gains `can_export` (default `False`).
- `SCREEN_OPERATION_ACTIONS["export"] = "export"`.
- RBAC path sets `can_export` from `screen.{key}.export`. The legacy fallback always denies export, because `txn.screen` has no `allow_export`.
- `ScreenPermissionsRead` gains `can_export`. This is an additive field on `GET /api/screens/{key}`.

Reports, in [`mtf/rpt/services/report_catalog.py`](../mtf/rpt/services/report_catalog.py):

- New `require_export(tenant_id, report_key)`.
- Not viewable: 404 `REPORT_NOT_FOUND`.
- Viewable but no `can_export`: 403 `REPORT_FORBIDDEN`.
- System users are allowed.

Tests: unit tests for both helpers, covering the RBAC and legacy paths.

## Item 9: report services fail closed

- `ReportRunService`, `ReportLookupService`, `ReportSavedViewService`, `ReportActionService`: `catalog` becomes required (drop the `or ReportCatalogService(db)` default).
- `ReportCatalogService.__init__`: if `user is None`, require an explicit `unrestricted=True`, otherwise raise `ValueError`.
- Update the tests that construct these without a catalog. `test_list_reports_without_user_does_not_filter_by_grants` passes `unrestricted=True`.

## Doc drift

- [rbac_database_design.md](rbac_database_design.md):
  - Deployment order matches steps 0 to 10.
  - Screens section: the RBAC-else-fallback rule, the operation mapping, and export.
  - Service-rules table: the last-admin wording.
  - New rules: portal report grants, the tenant-report exemption.
- [auth_rbac_schema_v3.sql](auth_rbac_schema_v3.sql) header: `screen_permission` is the fallback for tenants without RBAC grants.
- [rbac_development_steps.md](rbac_development_steps.md) and [docs/CONVENTIONS.md](../docs/CONVENTIONS.md): one bullet each for the export helpers, the portal report grants, and the tenant-report exemption.

## Verification

- `uv run ruff check` on touched files.
- Unit: `tests/auth`, `tests/rpt`, `tests/txn`.
- Live: backfill, tenant RBAC, report RBAC, and screen-access integration tests. Re-run the full suite once the SQL Server connection is stable.
