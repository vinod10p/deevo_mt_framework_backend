# deevo_mt_framework_backend

Multi-tenant framework backend for Deevo.

**Documentation:**

- [docs/CONVENTIONS.md](docs/CONVENTIONS.md) — architecture, API, database, and auth rules (source of truth)
- [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) — project scope and **current build step** (update as you work)
- [docs/LAYERING.md](docs/LAYERING.md) — api, model, schema, service responsibilities
- [docs/AI_SKILLS.md](docs/AI_SKILLS.md) — Cursor rules and skills (rationale and reference)

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- ODBC Driver 17 or 18 for SQL Server (when using `DB_TYPE=mssql` / pyodbc)

## Setup

```bash
uv sync --group dev
cp .env.example .env
```

## Run

Server listens on **http://localhost:8000** (`GET /health` for probes).

```bash
uv run python main.py
```

If port 8000 is already in use:

```bash
kill $(lsof -t -iTCP:8000 -sTCP:LISTEN)
```

Use **Ctrl+C** to stop the server (not Ctrl+Z — suspending leaves the port occupied).

Alternative:

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Test

All tests:

```bash
uv run pytest
```

Unit only (no live SQL Server):

```bash
DEEVO_SKIP_DB_TESTS=1 uv run pytest -m "not integration" -v
```

Integration only (requires `.env` SQL Server credentials):

```bash
uv run pytest -m integration -v
```

## Lint

```bash
uv run ruff check mtf tests main.py
```

## Cursor AI (rules and skills)

Project-specific guidance for Cursor agents lives in `.cursor/`:

| Path | Purpose |
|------|---------|
| [.cursor/rules/mtf-python.mdc](.cursor/rules/mtf-python.mdc) | Applies when editing `mtf/**/*.py` — points to CONVENTIONS + PROJECT_CONTEXT |
| [.cursor/skills/mtf-schema-change/](.cursor/skills/mtf-schema-change/) | SSMS DDL → `database_schema_v1.sql` → models → schemas → tests |
| [.cursor/skills/mtf-add-api-endpoint/](.cursor/skills/mtf-add-api-endpoint/) | New routes following `api/` → `services/` → models layering |
| [.cursor/skills/mtf-dev-and-test/](.cursor/skills/mtf-dev-and-test/) | Run server, pytest, integration gating, port conflicts |

Skills load when a task matches their description, or when you name them explicitly (e.g. “use mtf-schema-change skill”).

## Project structure

```
deevo_mt_framework_backend/
├── mtf/                  # Deevo Multi-Tenant Framework package
│   ├── shared/           # Shared config, database, security
│   ├── auth/             # Authentication & users
│   ├── tenant/           # Tenant management
│   └── audit/            # Audit logging
├── tests/
├── docs/
│   ├── CONVENTIONS.md       # Rules (stable)
│   ├── PROJECT_CONTEXT.md   # Scope + current step (workflow)
│   ├── LAYERING.md          # api / model / schema / service guide
│   ├── AI_SKILLS.md         # Cursor rules/skills reference
│   └── database_schema_v1.sql
├── .cursor/
│   ├── rules/               # File-scoped agent rules
│   └── skills/              # Task workflow skills
├── prompts/                 # Historical codegen prompts
├── third_party_licenses/
└── main.py               # Application entry point
```
