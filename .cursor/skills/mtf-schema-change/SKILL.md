---
name: mtf-schema-change
description: >-
  Syncs SQL Server DDL changes with MTF Python code. Use when altering tables in
  SSMS, adding columns, fixing model/DDL mismatch, updating database_schema_v1.sql,
  or when the user mentions schema change, DDL, or deevo_ddl.
disable-model-invocation: true
---

# MTF Schema Change Workflow

SQLAlchemy models **match** live SSMS DDL — not the other way around. Alembic is **not** used in v1.

Authoritative references:

- [docs/CONVENTIONS.md](../../../docs/CONVENTIONS.md) — Database, Schema changes (SSMS — v1)
- [docs/database_schema_v1.sql](../../../docs/database_schema_v1.sql) — canonical MTF DDL export
- [docs/PROJECT_CONTEXT.md](../../../docs/PROJECT_CONTEXT.md) — in-scope tables per module

## Checklist

Copy and track progress:

```
- [ ] 1. Write and run SSMS script as deevo_ddl
- [ ] 2. Update docs/database_schema_v1.sql (or add v2 file for major releases)
- [ ] 3. Update SQLAlchemy model(s) in mtf/**/models/
- [ ] 4. Update Pydantic schema(s) in mtf/**/schemas/ (or audit/schemas.py)
- [ ] 5. Update service(s) — queries, create/update payloads, soft-delete filters
- [ ] 6. Update API routes if request/response shape changed
- [ ] 7. Add or update tests (unit + integration if DB behavior changed)
- [ ] 8. Run unit tests, then integration tests against live SQL Server
```

## Step 1 — SSMS (deevo_ddl only)

- Apply DDL in **SQL Server Management Studio** logged in as **`deevo_ddl`**.
- **Never** run DDL from the running app (`deevo_app` is read/write only).
- Limit changes to MTF schemas: `auth`, `tenant`, `audit`, `rpt`, `txn`.
- Product schemas (`crm`, `email`, `scout`, `flow`) belong to other repos. `txn` is framework-owned metadata (screens, lookups, permissions) — not entity CRUD.

Optional: save the script under `docs/sql/` for history (team convention).

## Step 2 — Canonical DDL file

After SSMS apply succeeds, update [docs/database_schema_v1.sql](../../../docs/database_schema_v1.sql) to match live `deevo_app_dev2` (or your target DB).

For breaking or versioned releases, add `docs/database_schema_v2.sql` instead of overwriting v1.

`rpt` tables are not in `database_schema_v1.sql` — their DDL is
[docs/rpt_schema_v5.sql](../../../docs/rpt_schema_v5.sql); update that file instead.
`txn` tables (and V2 `rpt.report_permission` / `report_action` / `report_action_param` /
`permission_mode`) are in [docs/txn_schema_v2.sql](../../../docs/txn_schema_v2.sql).

## Step 3 — SQLAlchemy models

- `auth` / `tenant` / `rpt` / `txn`: one file per entity under `mtf/<domain>/models/`
- `audit`: flat `mtf/audit/models.py`
- Match column names, types, nullability, and SQL schema (`__table_args__ = {"schema": "auth"}` etc.)
- Include `row_version`, `is_deleted`, `deleted_by`, audit columns where the table has them

## Step 4 — Pydantic schemas

- Create / Read / Update / List variants as needed
- Use `@field_validator` for JSON bytes — not invalid Pydantic v1 patterns
- PATCH schemas: optional fields only; send `row_version` as base64 for concurrency

## Step 5 — Services

- Generate ULIDs in services (`python-ulid`)
- All list/get queries: `is_deleted == False` unless intentionally listing deleted rows
- Use `mtf.shared.exceptions`: `not_found`, `conflict`, `bad_request`
- Handle `IntegrityError` via `mtf.shared.db_integrity` where applicable

## Step 6 — API

- Thin routers only — delegate to services
- Register new routers in `mtf/<domain>/api/__init__.py`
- Mount prefix already set in [main.py](../../../main.py): `/api/auth`, `/api/tenant`, `/api/audit`,
  and `/api` for `rpt` (`/reports`) and `txn` (`/screens`)

## Step 7 — Tests

- Unit: `DEEVO_SKIP_DB_TESTS=1 uv run pytest -m "not integration" -v`
- Integration: `uv run pytest -m integration -v` (requires `.env` SQL Server credentials)
- Mark integration modules: `pytestmark = pytest.mark.integration`
- Integration tests should clean up created rows (soft-delete pattern in existing tests)

## Out of scope guard

If the change targets CRM/product tables, stop — implement in `deevo_crm_backend` or the relevant product repo.
