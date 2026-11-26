# Prompt — split deevoflow_backend into the new deevo_* repos

> Give this whole file to the AI tool working in **deevoflow_backend**. Also give it
> `deevo_mt_framework_backend/docs/architecture.md` and `docs/security.md` (or let it read them
> from `../deevo_mt_framework_backend/docs/`). Those two documents are the source of truth; this
> prompt is the step-by-step plan.

---

## Your role

You are helping move the backend of the Deevo platform out of the current repo,
**`deevoflow_backend`**, into a set of new repos. You work **one phase at a time**, and stop
at the end of each phase for the user to review. The user commits manually.

## Working rules (non-negotiable)

1. **Before making any change, say which repo and which git branch you are on.**
2. **Never commit, push, stash, reset or rebase.** Leave changes uncommitted; the user reviews
   and commits.
3. **One phase at a time.** At the end of each phase, stop, summarise what changed and what is
   not done, and wait for the user to say "next".
4. **`deevoflow_backend` is frozen.** Do not change its code. The only files you may add there
   are the migration notes in `docs/migration/` (Phase 0).
5. **Never modify `deevo_mt_framework_backend`** (package `mtf`). If the framework needs a
   change, write it down in `docs/migration/framework_requests.md` for the user.
6. **Do not touch** `deevoflow_react`, `deevo_admin` or any repo not named in this prompt.
7. **Move, don't rewrite.** Business logic, SQL, table names, URLs and response shapes stay
   the same. The goal is the same behaviour in a new structure. Refactors come after cutover.
8. **Tests prove it.** Every moved piece keeps its tests; new tests must fail on broken code and
   pass on correct code. Never weaken or delete a test to make it pass — ask instead.
9. Never print or copy secret values from `.env` files into code, docs or chat.

---

## Background

### Today

- `deevo_mt_framework_backend` (package **`mtf`**) — reusable multi-tenant framework: auth,
  sessions, tenants, RBAC, audit, reports (`rpt`), transaction screens (`txn`), navigation
  (`nav`). Owns SQL schemas `auth`, `tenant`, `audit`, `rpt`, `txn`, `nav`.
- `deevoflow_backend` — FastAPI app that installs `mtf`, mounts its routers under `/api/v1`
  and adds the product: text / WhatsApp / email integration, CRM, tenant and customer
  features, workflow. Product SQL schemas include `crm`, `email`, `flow`, `scout` (confirm in
  Phase 0).
- `deevoflow_react` — the frontend; talks to one API URL.

### Target

| Repo | Kind | Contents |
|---|---|---|
| `deevo_api` | **The only deployable app** | `main.py` that composes the packages, worker entry point, exact version pins (`uv.lock`), CORS, composed-app tests. Almost no business logic |
| `deevo_integration` | Platform package | Email, WhatsApp, SMS: providers, credentials, templates, sending, receiving, retries, delivery status, webhooks |
| `deevo_crm` | Domain package | CRM (leads, contacts, accounts, deals, activities, …) |
| `deevo_workflow` | Package (layer to confirm) | Workflow definitions and runs |
| later | Domain packages | `deevo_inventory`, `deevo_accounting`, `deevo_forecasting` |

Dependencies point **down only**:

```
deevo_crm   deevo_workflow   (later: inventory, accounting, forecasting)   ← never import each other
        \        /
     deevo_integration                                                     ← never imports a domain
            |
   deevo_mt_framework_backend (mtf)
```

- A domain never imports another domain. Cross-domain features are wired in `deevo_api` or
  through events.
- `deevo_integration` never calls a domain. It **publishes events** (`message_received`,
  `email_received`, `delivery_failed`, …) and offers `send(...)`; domains subscribe.
- If something you find does not fit these rules, **do not bend the rules** — list it in the
  Phase 0 inventory as a decision for the user.

### Naming convention

`deevo_<one spelled-out word>`; no abbreviations. Repo name = Python package name = settings
prefix stem = DB login stem:

| Module | Repo / package | `DEEVO_MODULES` value | Settings prefix | DB login (target) |
|---|---|---|---|---|
| Integration | `deevo_integration` | `integration` | `DEEVO_INTEGRATION_*` | `deevo_integration_app` |
| CRM | `deevo_crm` | `crm` | `DEEVO_CRM_*` | `deevo_crm_app` |
| Workflow | `deevo_workflow` | `workflow` | `DEEVO_WORKFLOW_*` | `deevo_workflow_app` |

**SQL schemas keep their current names** (`crm`, `email`, `flow`, …) through the cutover —
same database, no renames, so the old backend can still run against it for rollback. Renaming
schemas to match module names is a later, separate change.

Shared settings (JWT, CORS, database server, `DEEVO_ENVIRONMENT`, …) keep the existing
`DEEVO_*` names read by `mtf`.

### Timeline

The user wants to cut over in a few days: build and test the new repos side by side, then
switch Azure from `deevoflow_backend` to `deevo_api` in one step, keeping the old app
deployed (workers stopped) for 1–2 weeks as rollback. See `architecture.md` §12.

---

## Phase 0 — Inventory (in `deevoflow_backend`, docs only)

Read the whole repo first. Then create `docs/migration/inventory.md` with:

1. **Module map** — every Python package / folder in `deevoflow_backend`, and which target
   repo it moves to (`deevo_api`, `deevo_integration`, `deevo_crm`, `deevo_workflow`, or
   "stays in mtf / already in mtf", or **"decision needed"**).
2. **Routes** — every route (method + path + auth dependency + target repo). Generate it from
   the app (e.g. iterate `app.routes`) rather than by reading code. Save the raw list as
   `docs/migration/routes_before.txt`.
3. **OpenAPI** — save `docs/migration/openapi_before.json` from the running app.
4. **Models and tables** — every SQLAlchemy model: schema.table, owning target repo, and every
   foreign key or query that crosses module boundaries.
5. **Cross-module imports** — every import from one future module into another (e.g. CRM code
   importing integration internals, integration importing CRM). These are the places that
   need events or wiring in `deevo_api`. Show file and line.
6. **Background work** — schedulers, pollers, email sync, webhook consumers, startup tasks,
   threads, cron. For each: what it does, how it is started today, target repo.
7. **Middleware, startup hooks, exception handlers, global settings** — these belong in
   `deevo_api`, never in a package.
8. **Settings / env vars** — every setting read (name only, never the value), current
   prefix, target prefix.
9. **External URLs registered outside the app** — Microsoft Entra redirect URIs, WhatsApp/SMS
   webhook URLs, Microsoft Graph subscriptions, anything the frontend hard-codes.
10. **Tests** — test folders and which repo each moves to; current pass/fail counts.
11. **Security follow-ups** — run the grep below and list hits against tasks B1–B10 in
    `security.md` §2.2:

    ```bash
    grep -rnE "from jose|import jose|create_access_token|decode_token|def get_current_user|CORSMiddleware|audit/logs" --include=*.py . | grep -v "/.venv/"
    ```

12. **Decisions needed** — at least:
    - Is `deevo_workflow` a domain (independent, like CRM) or a shared layer that domains call?
    - Where do tenant-level product features and **customer** live (`mtf`, `deevo_crm`, own repo)?
    - Email: `mtf` already has mailbox models and the Microsoft OAuth flow (`email.mailbox`,
      `email.mailbox_credential`). Does the rest of email live in `deevo_integration`, and is
      the `email` schema shared?
    - What is `scout`, and where does it go?
    - Anything that breaks the dependency rules.

**Stop. Wait for the user to answer the decisions.**

---

## Phase 1 — Capture current behaviour (in `deevoflow_backend`, tests only)

Goal: a way to prove the new stack behaves like the old one.

1. Under `tests/contract/` (a new folder; no code changes), write a **recorder** that runs a
   fixed list of requests against the old app on the test database and saves the responses
   as JSON "golden" files: login, refresh, `/auth/me`, the main list/detail/create/update
   calls of each CRM entity, integration endpoints, workflow endpoints, a few 401/403/404
   cases.
2. Normalise volatile fields (ids, timestamps, tokens) so files are comparable.
3. The same request list will run against `deevo_api` in Phase 5; responses must match.

**Stop for review.**

---

## Phase 2 — Create the repo skeletons

Create sibling folders under the same parent folder as `deevoflow_backend`
(e.g. `../deevo_api`, `../deevo_integration`, `../deevo_crm`, `../deevo_workflow`). First
check that no folder or GitHub repo with that name exists — `deevo_crm` has been used as a
frontend app name in older framework docs; if anything clashes, stop and ask. `git init`
each folder; **the user creates the GitHub remotes and commits**.

Match `deevo_mt_framework_backend` conventions: Python ≥ 3.13, **uv**, hatchling, flat
package layout, ruff, pytest, the `api / models / schemas / services` layering
(`docs/LAYERING.md` in the framework).

### Every package repo (`deevo_integration`, `deevo_crm`, `deevo_workflow`)

```
deevo_crm/
├── pyproject.toml          # name "deevo-crm"; depends on mtf (+ deevo-integration for domains)
├── README.md
├── CLAUDE.md / AGENTS.md   # boundaries for AI tools (below)
├── deevo_crm/
│   ├── __init__.py
│   ├── module.py           # the package's public contract (below)
│   ├── config.py           # Settings(BaseSettings), env_prefix="DEEVO_CRM_"
│   ├── database.py         # own engine/session factory (see "Database" below)
│   ├── events.py           # events it publishes / handlers it subscribes (if any)
│   └── <entity>/api|models|schemas|services/
├── sql/                    # DDL / migrations for its own schema only
└── tests/
    ├── conftest.py         # includes the login-throttle reset fixture (security.md B5)
    ├── critical/           # tenant isolation, permissions, money/state rules — protected
    └── ...
```

**`module.py` contract** — the only thing `deevo_api` imports from a package:

```python
from fastapi import APIRouter

NAME = "crm"  # the DEEVO_MODULES value

def routers() -> list[tuple[str, APIRouter]]:
    """(prefix, router) pairs; prefixes must equal today's URLs exactly."""
    ...

def worker_tasks() -> list[...]:
    """Background jobs / event handlers this package runs in the worker process."""
    ...
```

A package must **not**: add middleware, change global settings, monkeypatch, register
startup hooks that touch shared state, create its own FastAPI app for production, create or
decode JWTs itself (always use `mtf.shared.deps.get_current_user` / `require_*`), or import
`jose`.

**Database:** each package gets its own engine factory reading `DEEVO_<MODULE>_DB_USER` /
`DEEVO_<MODULE>_DB_PASSWORD`, **falling back to the shared app login** when those are not set.
That keeps the cutover simple (one login, as today) and lets per-module logins be switched on
later without code changes. Production TLS rules from `mtf` (`Encrypt=yes`,
`TrustServerCertificate=no`) apply to every engine — reuse `mtf`'s URL builder rather than
writing a new one.

**`CLAUDE.md` / `AGENTS.md`** in each repo states: what the package owns, which schemas it may
write, that it must not import other domains, the `module.py` contract, the "never commit"
and "say the branch first" rules, and how to run the tests.

**CI (GitHub Actions)** in each repo: `ruff`, tests, `import-linter`, `pip-audit`, `gitleaks`.

### `deevo_api`

```
deevo_api/
├── pyproject.toml     # depends on mtf + every package, exact versions; uv.lock committed by user
├── main.py            # builds the FastAPI app (below)
├── worker.py          # runs worker_tasks() of enabled modules
├── deevo_api/
│   ├── modules.py     # explicit map: {"integration": "deevo_integration.module", ...}
│   └── wiring.py      # cross-domain glue, event subscriptions
├── .env.example
└── tests/
    ├── test_routes_snapshot.py   # full route + middleware list == approved snapshot
    ├── test_import_rules.py      # or import-linter config in pyproject.toml
    └── contract/                 # Phase 1 golden files, replayed here
```

`main.py`:
- Mounts the `mtf` routers exactly as `deevoflow_backend` does today.
- Mounts each enabled module's `routers()` from `modules.py`, filtered by
  `DEEVO_MODULES` (default: all).
- Owns all middleware. CORS exactly as in `security.md` §2.2 B4 (`settings.allowed_origins`,
  `cors_allow_credentials`, explicit methods, `expose_headers=["Retry-After"]`).
- Copies any other middleware / exception handlers found in Phase 0, unchanged.

`import-linter` contracts (in `deevo_api`'s `pyproject.toml`):

```toml
[tool.importlinter]
root_packages = ["deevo_crm", "deevo_workflow", "deevo_integration", "mtf"]

[[tool.importlinter.contracts]]
name = "Domains are independent"
type = "independence"
modules = ["deevo_crm", "deevo_workflow"]

[[tool.importlinter.contracts]]
name = "Layers point down"
type = "layers"
layers = ["deevo_crm | deevo_workflow", "deevo_integration", "mtf"]
```

(Adjust for the Phase 0 decision on `deevo_workflow`.)

During development, install the packages as **editable path dependencies** (`uv add --editable
../deevo_crm`). Switching to git tags / pinned versions is a later step for the user.

**Stop for review.**

---

## Phase 3 — Move `deevo_integration`

1. Copy the integration code, its models, SQL and tests from `deevoflow_backend` into
   `deevo_integration`. Record the source commit SHA in `deevo_integration/MIGRATION.md`.
2. Fix imports; remove every import of CRM / workflow code. Where integration used to call a
   domain directly, publish an event instead (outbox table written in the same transaction;
   consumed by the worker). Document each event's payload as a versioned contract in
   `events.py`.
3. Move pollers, email sync, webhook handlers into `worker_tasks()`. Webhook **routes** keep
   their exact current URLs.
4. Run its tests; then run them mounted in `deevo_api`.

**Stop for review.**

## Phase 4 — Move `deevo_crm`, then `deevo_workflow`

Same steps as Phase 3, one package at a time, stopping after each:
- Copy code + tests, record source SHA.
- Replace imports of integration internals with `deevo_integration`'s public API
  (`send(...)`, event subscriptions).
- Replace any domain-to-domain import with wiring in `deevo_api/wiring.py` or events.
- Same URLs, same response shapes, same tables.
- `tests/critical/`: tenant isolation (a user of tenant A can never read/write tenant B),
  permission checks per route, any state or money rules.

## Phase 5 — Prove equivalence

In `deevo_api`, against the test database:

1. **Routes:** `routes_after.txt` equals Phase 0 `routes_before.txt` (same methods, paths,
   auth dependencies). Any difference is explained or fixed.
2. **OpenAPI:** diff against `openapi_before.json` (e.g. `oasdiff`); no breaking changes.
3. **Contract tests:** replay Phase 1 golden requests; all responses match.
4. **Full test suites** of every repo green (except failures that also fail in the old repo —
   list those explicitly).
5. **Security tasks B1–B10** (`security.md` §2.2) all done in `deevo_api` and the packages.
6. **No duplicate workers:** document exactly which background jobs exist and how to stop the
   old ones.

Write `deevo_api/docs/cutover_report.md` with the results. **Stop for review.**

## Phase 6 — Cutover support (the user runs it)

Prepare, don't execute: write `deevo_api/docs/cutover_runbook.md` from `architecture.md` §12:

- Azure app settings for `deevo_api` (names only; production values from `security.md` §1).
- External URLs to change, with **old and new values** side by side (Entra redirect URIs,
  WhatsApp/SMS webhooks, Graph subscriptions, frontend API base URL).
- Order: deploy to staging slot → smoke test → **stop old workers** → swap → start new
  workers → watch 401/403/429/5xx for an hour.
- Rollback: swap back, restore external URLs, restart old workers.
- After 1–2 quiet weeks: archive `deevoflow_backend`.

---

## Definition of done

- Four repos exist, each with skeleton, `CLAUDE.md` / `AGENTS.md`, CI config and green tests.
- `deevo_api` serves every route `deevoflow_backend` serves, at the same URLs, with
  matching contract tests.
- Import rules enforced in CI; no domain imports another; integration imports no domain.
- No middleware or global settings outside `deevo_api`.
- Security tasks B1–B10 complete.
- Cutover runbook ready; nothing committed by you.
