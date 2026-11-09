# Deevo Multi-Tenant Framework

FastAPI backend library (`mtf`) for multi-tenant products: authentication, tenants and accounts, audit logging, a generic report writer, and generic transaction-screen metadata.

**Author:** Vinod Jain  
**Copyright:** [Deevolight LLC](LICENSE) (MIT License)

This repository is the framework, not a CRM. Product backends such as DeevoFlow depend on the `mtf` package, mount its routers, seed report and screen rows, and implement their own entity APIs (Lead, Account, …).

## What it provides

| Area | Package | HTTP (this app’s `main.py`) |
|------|---------|------------------------------|
| Health | — | `GET /health` (no auth) |
| Auth | `mtf.auth` | `/api/auth` — login, refresh, users, memberships |
| Tenant | `mtf.tenant` | `/api/tenant`, `/api/account` |
| Audit | `mtf.audit` | `/api/audit` |
| Reports | `mtf.rpt` | `/api/reports` — catalog, lookups, `/run`, saved views, actions + resolve |
| Screens | `mtf.txn` | `/api/screens/{screen_key}` — metadata only; `require_screen_permission()` for product routes |

Tenant identity always comes from the JWT, never from the client body. Public (no Bearer): `GET /health`, `POST /api/auth/login`, `POST /api/auth/refresh`. Interactive API docs: `http://localhost:8000/docs` when the server is running.

## What it does not provide

- Product tables or CRUD (`crm.lead`, invoices, …)
- Dynamic SQL generated from screen metadata
- Alembic migrations — DDL is applied in SSMS (`deevo_ddl`); the app uses `deevo_app`

## How a product uses it

1. Depend on `deevo-mt-framework-backend` (local: path/editable; Azure: the version on `main`).
2. Apply framework SQL: [docs/database_schema_v1.sql](docs/database_schema_v1.sql) (auth, tenant, audit), [docs/rpt_schema_v5.sql](docs/rpt_schema_v5.sql), [docs/txn_schema_v2.sql](docs/txn_schema_v2.sql).
3. Mount the routers (products often use prefix `/api/v1`):

```python
from mtf.rpt.api import router as mtf_rpt_router
from mtf.txn.api import router as mtf_txn_router
from mtf.txn.api.deps import require_screen_permission

app.include_router(mtf_rpt_router, prefix="/api/v1")
app.include_router(mtf_txn_router, prefix="/api/v1")
```

4. Seed `rpt.*` and `txn.*` for each report and screen. Implement entity GET/POST/PATCH/DELETE yourself; gate writes with `require_screen_permission("your_screen_key", "view"|"add"|"edit"|"delete")`. If the tenant has RBAC grants for that screen, the helper checks `screen.{key}.{action}` only; otherwise it falls back to `txn.screen_permission`.

Sample system reports: [docs/rpt_seed_sample_report.sql](docs/rpt_seed_sample_report.sql).

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- ODBC Driver 17 or 18 for SQL Server
- SQL Server with the framework schemas applied

## Run locally

```bash
uv sync --group dev
cp .env.example .env   # set DEEVO_MSSQL_* and DEEVO_JWT_SECRET_KEY
uv run python main.py
```

Server: **http://localhost:8000** (`GET /health` for probes).

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Stop with Ctrl+C. If port 8000 is already in use: `kill $(lsof -t -iTCP:8000 -sTCP:LISTEN)`.

## Test and lint

```bash
DEEVO_SKIP_DB_TESTS=1 uv run pytest -m "not integration" -v   # unit only
uv run pytest -m integration -v                                 # needs live SQL Server
uv run ruff check mtf tests main.py
```

## Versioning

Package version is the date in `pyproject.toml` (e.g. `2026.10.16`). Before merging to `main` for Azure:

```bash
uv lock
```

Commit `pyproject.toml` and `uv.lock` together.

## Repository layout

```
mtf/           # installable package
  shared/      # config, database, JWT, errors
  auth/
  tenant/
  audit/
  rpt/         # generic reports
  txn/         # generic screen metadata
tests/
docs/          # conventions, DDL, design
prompts/       # API/frontend contracts for product apps
main.py        # standalone server used in development
```

## Documentation

| Doc | For |
|-----|-----|
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | Coding rules (IDs, errors, JWT, SQL) |
| [docs/LAYERING.md](docs/LAYERING.md) | `api` → `services` → models |
| [docs/REPORTING_FRAMEWORK_CONTEXT.md](docs/REPORTING_FRAMEWORK_CONTEXT.md) | Report writer design |
| [prompts/rpt/REPORT_API_PROMPT.md](prompts/rpt/REPORT_API_PROMPT.md) | Report HTTP contract |
| [prompts/rpt/REPORT_FRONTEND_PROMPT.md](prompts/rpt/REPORT_FRONTEND_PROMPT.md) | Reports React contract |
| [prompts/rpt/REPORT_FRONTEND_REPORT_DRILLDOWN_PROMPT.md](prompts/rpt/REPORT_FRONTEND_REPORT_DRILLDOWN_PROMPT.md) | Report → report drilldown |
| [prompts/txn/TRANSACTION_FRONTEND_PROMPT.md](prompts/txn/TRANSACTION_FRONTEND_PROMPT.md) | Transaction-screen React contract |
| [LICENSE](LICENSE) | MIT |

Cursor rules and skills (for contributors using Cursor) live in [`.cursor/`](.cursor/). See [docs/AI_SKILLS.md](docs/AI_SKILLS.md).
