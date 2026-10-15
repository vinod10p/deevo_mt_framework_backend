# Project Context — deevo_mt_framework_backend

Lightweight orientation for humans and AI assistants.
**Coding rules live in [CONVENTIONS.md](CONVENTIONS.md)** — do not duplicate them here.
Update this file when the **current step** or **scope** changes.

---

## Project

| Item | Value |
|------|-------|
| **Project** | `deevo_mt_framework_backend` |
| **Package** | `mtf` (Deevo Multi-Tenant Framework) |
| **Stack** | FastAPI, SQLAlchemy 2.0, Pydantic v2, SQL Server, pyodbc, uv |
| **Python** | >= 3.11 |
| **Runs on** | `http://localhost:8000` |
| **Conventions** | [CONVENTIONS.md](CONVENTIONS.md) — authoritative |

---

## Database (DDL)

| Item | Decision |
|------|----------|
| **Tables** | Already exist on SQL Server — created and managed in **SSMS** |
| **Canonical DDL** | [database_schema_v1.sql](database_schema_v1.sql) — SSMS export for `deevo_app_dev2` (v1) |
| **ORM role** | SQLAlchemy models must **match** live DDL (not the other way around) |
| **Alembic** | **Not used** in this repo for v1 — schema changes are scripts you run in SSMS |
| **Runtime user** | `deevo_app` (read/write, no DDL) via `.env` |
| **DDL user** | `deevo_ddl` only when you execute change scripts in SSMS (never in the app) |

When you change a table in SSMS, update [database_schema_v1.sql](database_schema_v1.sql) (or add `database_schema_v2.sql`) and the matching `mtf/**/models` (and schemas/services) in the same change.

---

## Current Step

Update statuses as work progresses.

| Step | Description | Status |
|------|-------------|--------|
| 1 | Project scaffold, `pyproject.toml`, folder layout, docs | ✅ Done |
| 2 | `shared/` — config, database, security, deps, exceptions, `db_integrity` | ✅ Done |
| 2b | `shared/schemas.py` (shared Pydantic helpers, e.g. `row_version`) | ⬜ Pending |
| 3 | `auth/` models | ✅ Done |
| 4 | `tenant/` models | ✅ Done |
| 5 | `auth/` schemas | ✅ Done |
| 6 | `tenant/` schemas | ✅ Done |
| 7 | `auth/` services | ✅ Done |
| 8 | `tenant/` services | ✅ Done |
| 9 | `auth/` + `tenant/` API routers | ✅ Done |
| 10 | `audit/` — models, schemas, service, router | 🔄 In progress |
| 11 | Verify SQLAlchemy models match [database_schema_v1.sql](database_schema_v1.sql) / SSMS | ⬜ Pending |
| 12 | `main.py` — app entry, CORS, mount routers, `GET /health` | ✅ Done |
| 13 | Tests — `conftest`, auth, tenant, audit (+ `@pytest.mark.integration`) | ⬜ Pending |
| 14 | `rpt/` Phase 1 — report catalog read service (`GET /api/reports`, `GET /api/reports/{report_key}`) | ✅ Done |
| 15 | `rpt/` Phase 2 — execution engine: lookups + `/run` (parameterized proc call, tenant session context) | ✅ Done |
| 16 | `rpt/` Phase 3 — saved view CRUD (`report_saved_view`) + User → Tenant → System default | ⬜ Pending |
| 17 | `txn/` models — screen, section, field, lookup, permission + V2 `rpt` metadata | ✅ Done |
| 18 | `txn/` PermissionService (screens only) + `require_screen_permission()` | ✅ Done |
| 19 | `txn/` Screen metadata API `GET /api/screens/{screen_key}` | ✅ Done |
| 20 | `rpt/` embed `actions[]` on `GET /api/reports/{report_key}` | ✅ Done |
| 21 | `rpt/` `POST /api/reports/{report_key}/actions/{action_key}/resolve` | ✅ Done |

---

## Scope

### In Scope

| Python module | SQL schema | Tables |
|---------------|-----------|--------|
| `mtf/shared` | — | config, database, security, deps, exceptions, schemas |
| `mtf/auth` | `auth` | `app_user`, `session`, `tenant_user`, `tenant_account_user` |
| `mtf/tenant` | `tenant` | `tenant`, `tenant_setting`, `tenant_account`, `tenant_account_address` |
| `mtf/audit` | `audit` | `audit_log` (append-only) |
| `mtf/rpt` | `rpt` | `report_definition` (incl. `permission_mode`), `report_column`, `report_criteria`, `report_saved_view`, `report_permission`, `report_action`, `report_action_param` — see [REPORTING_FRAMEWORK_CONTEXT.md](REPORTING_FRAMEWORK_CONTEXT.md) |
| `mtf/txn` | `txn` | `screen`, `screen_section`, `screen_field`, `screen_field_config`, `lookup`, `lookup_column`, `screen_permission` — generic transaction-screen metadata only (DDL: [txn_schema_v2.sql](txn_schema_v2.sql)) |

### Out of Scope

Product domains are **not** implemented here — `crm`, `email`, `scout`, `flow`, and entity CRUD (Lead, Customer, …). Those belong to product backends such as `deevoflow_backend`. Products seed `txn.screen` rows and implement entity APIs; they must not add generic metadata services here.

Products may share the same SQL Server instance but must never write to
`auth.*`, `tenant.*`, `audit.*`, `rpt.*`, or `txn.*` tables directly (only via this API, or documented seed scripts).

---

## API Surface (mount points)

| Prefix | Domain | Notes |
|--------|--------|--------|
| `GET /health` | — | No auth; load balancers |
| `/api/auth` | `mtf.auth` | login, refresh, users, memberships |
| `/api/tenant` | `mtf.tenant` | tenants, accounts, settings, addresses |
| `/api/account` | `mtf.tenant` (portal) | account self-service — users menu (`tenant_account` scope) |
| `/api/audit` | `mtf.audit` | read/create audit log (append-only) |
| `/api/reports` | `mtf.rpt` | report catalog metadata (`tenant` + `tenant_account` scope) |
| `/api/screens` | `mtf.txn` | generic screen metadata (`GET /{screen_key}`; JWT tenant required) |

Public (no Bearer token): `GET /health`, `POST /api/auth/login`, `POST /api/auth/refresh`.

---

## Quick Pointers

Full details and examples are in [CONVENTIONS.md](CONVENTIONS.md).

| Topic | Value |
|-------|-------|
| All IDs | ULID `VARCHAR(26)` |
| Login table | `auth.app_user` — not `auth.user` |
| User scope values | `system` \| `tenant` \| `tenant_account` |
| User type values | `system` \| `tenant` \| `tenant_account` |
| Soft delete | `is_deleted` + `deleted_by`; every list query filters `is_deleted = False` |
| Layering | `api/` (HTTP only) → `services/` → models |
| Audit layout | Flat — `models.py`, `schemas.py`, `service.py` (no subpackages) |
| Errors | `{"code": "DOMAIN_ENTITY_REASON", "message": "..."}` |
| Concurrency | `row_version` (ROWVERSION) on all mutable tables |
| Config | `DEEVO_*` vars in `.env`, loaded by `mtf/shared/config.py` |
| DB users | Runtime `deevo_app`; DDL changes in SSMS as `deevo_ddl` (never in running app) |
| Schema changes | SSMS only (no Alembic in this repo for v1) |
| Tokens | Never stored raw — SHA-256 hashed as `BINARY(32)` |
| Seed user | `id = 01HYSTEM00000000000000000`, `user_scope = system` |
| Integration tests | `DEEVO_SKIP_DB_TESTS=1` or `pytest -m "not integration"` |

---

## Frontend Applications

| App | Tech | Scope | Port |
|-----|------|-------|------|
| `deevo_admin` | Streamlit | `system` | 8501 |
| `deevo_crm` | React | `tenant` | 3000 |
| `deevo_portal` | React | `tenant_account` | 3001 |
| `deevo_account_st` | Streamlit | `tenant_account` | 8502 |

All frontends call this backend via HTTP at `http://localhost:8000` (and/or their product backend where applicable).

---

## Related Docs

| File | Purpose |
|------|---------|
| [CONVENTIONS.md](CONVENTIONS.md) | Full coding rules — authoritative |
| [LAYERING.md](LAYERING.md) | api, model, schema, service responsibilities |
| [database_schema_v1.sql](database_schema_v1.sql) | Canonical MTF table DDL (auth, tenant, audit) |
| [REPORTING_FRAMEWORK_CONTEXT.md](REPORTING_FRAMEWORK_CONTEXT.md) | Generic reporting framework design (`rpt`) |
| [rpt_schema_v5.sql](rpt_schema_v5.sql) | Canonical `rpt` table DDL (V2 additions are in txn_schema_v2.sql) |
| [txn_schema_v2.sql](txn_schema_v2.sql) | Canonical `txn` table DDL + report permission/action tables |
| [rpt_seed_sample_report.sql](rpt_seed_sample_report.sql) | Grants + five sample system reports (accounts, account summary, addresses, staff users, portal users) and their lookup procs; delete-and-reinsert, re-runnable |
| [../prompts/rpt/REPORT_API_PROMPT.md](../prompts/rpt/REPORT_API_PROMPT.md) | Report API spec — rules, error codes, endpoints, build order |
| [../prompts/rpt/REPORT_FRONTEND_PROMPT.md](../prompts/rpt/REPORT_FRONTEND_PROMPT.md) | Report frontend contract — copied into each consuming app |
| [../prompts/rpt/NEW_REPORT_PROMPT.md](../prompts/rpt/NEW_REPORT_PROMPT.md) | Adding a report — procs, metadata rows per table, worked example, checks |
| [../prompts/txn/DEEVOFLOW_LEAD_SCREEN.md](../prompts/txn/DEEVOFLOW_LEAD_SCREEN.md) | DeevoFlow product prompt — mount `mtf.txn`, seed Lead screen, lookups, envelope CRUD |
| [../prompts/txn/DEEVOFLOW_LEAD_REPORT_ACTIONS.md](../prompts/txn/DEEVOFLOW_LEAD_REPORT_ACTIONS.md) | DeevoFlow product prompt — seed Lead list report → Lead screen actions |
| [../prompts/txn/TRANSACTION_FRONTEND_PROMPT.md](../prompts/txn/TRANSACTION_FRONTEND_PROMPT.md) | Transaction screen React contract — copied into each consuming frontend |
| [../README.md](../README.md) | Setup, install, run commands, Cursor rules/skills |
| [../.cursor/rules/mtf-python.mdc](../.cursor/rules/mtf-python.mdc) | Agent rule for `mtf/**/*.py` |
| [AI_SKILLS.md](AI_SKILLS.md) | Cursor rules/skills rationale and reference |
| [../.cursor/skills/](../.cursor/skills/) | Task workflow skills (schema change, add endpoint, dev/test) |
| [../prompts/](../prompts/) | Historical codegen prompts |
