---
name: mtf-dev-and-test
description: >-
  Runs the MTF backend locally, executes pytest unit and integration suites, and
  resolves port 8000 conflicts. Use when starting the server, running tests,
  DEEVO_SKIP_DB_TESTS, integration markers, address already in use, or uv commands.
disable-model-invocation: true
---

# MTF Dev and Test

Project: `deevo_mt_framework_backend` · package `mtf` · default port **8000**.

## Setup (once per clone)

```bash
uv sync --group dev
cp .env.example .env   # fill SQL Server + JWT values
```

Python 3.11+. ODBC Driver 17 or 18 for SQL Server when using pyodbc.

## Run the server

```bash
uv run python main.py
```

- Listens on `http://0.0.0.0:8000` (localhost:8000)
- Auto-reload when `DEEVO_DEBUG=true` in `.env`
- Health probe: `GET http://localhost:8000/health`

Alternative:

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Stop the server with Ctrl+C** — not Ctrl+Z. Suspending (^Z) leaves port 8000 occupied.

## Port 8000 already in use

Find and kill the listener (macOS):

```bash
kill $(lsof -t -iTCP:8000 -sTCP:LISTEN)
```

Force if needed:

```bash
kill -9 $(lsof -t -iTCP:8000 -sTCP:LISTEN)
```

Verify port is free:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

(no output = free)

## Test commands

| Goal | Command |
|------|---------|
| All tests | `uv run pytest` |
| Unit only (no live DB) | `DEEVO_SKIP_DB_TESTS=1 uv run pytest -m "not integration" -v` |
| Integration only | `uv run pytest -m integration -v` |
| Single file | `uv run pytest tests/tenant/test_tenant_api_integration.py -v` |
| Lint | `uv run ruff check mtf tests main.py` |

Integration tests require live SQL Server credentials in `.env` (`DEEVO_MSSQL_*`).

Skip integration without env flag on each run:

```bash
export DEEVO_SKIP_DB_TESTS=1   # or set in .env
```

Pytest marker defined in [pyproject.toml](../../../pyproject.toml):

```toml
integration: requires live SQL Server and credentials in .env
```

Integration test files use module-level:

```python
pytestmark = pytest.mark.integration
```

And often:

```python
def _skip_if_disabled() -> None:
    if os.environ.get("DEEVO_SKIP_DB_TESTS", "").lower() in ("1", "true", "yes"):
        pytest.skip("DEEVO_SKIP_DB_TESTS is set")
```

## Integration test auth stub

Many integration tests override `get_current_user` to act as seed system user `01HYSTEM00000000000000000`. See `tests/tenant/conftest.py` and `tests/auth/conftest.py`.

## Verify DB connectivity

```bash
uv run pytest tests/shared/test_database_connection.py -m integration -v
```

## API smoke (manual)

```bash
curl http://localhost:8000/health
# Login (adjust email/password):
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"your_password"}'
```

## Docs pointer

- Rules: [docs/CONVENTIONS.md](../../../docs/CONVENTIONS.md)
- Scope / current step: [docs/PROJECT_CONTEXT.md](../../../docs/PROJECT_CONTEXT.md)
