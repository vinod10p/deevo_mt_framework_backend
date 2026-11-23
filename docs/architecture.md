# Deevo platform architecture — repos, deployment and release safety

Status: **proposed** · Date: 2026-11-22 · Companion docs: [security.md](security.md),
[frontend_security.md](frontend_security.md)

This records how the Deevo backend is split into repositories, how it is deployed on Azure,
and how releases are kept safe when most code is written by AI tools.

---

## 1. Context and goals

| Goal | What it means in practice |
|---|---|
| **Independent domains** | CRM, inventory, accounting (and later forecasting, …) do not depend on each other. Each depends only on the platform: `deevo_mt_framework_backend` and integration |
| **Independent release schedules** | A domain can be released without releasing the others |
| **Frozen modules stay safe** | Once a domain (e.g. accounting) is in production, developing and releasing another domain must not change it — and we must be able to *prove* it did not |
| **AI-written code** | Code is mostly produced by AI tools (Claude, Cursor, Codex), so line-by-line review cannot be the main safety net. Automated, tamper-resistant checks are |
| **One Azure deployment** | A single API, `deevoflow_backend`, serves the frontend. All other repos are mounted into it |

---

## 2. Decision summary

1. **One repo per package**, released as versioned Python packages.
2. **`deevoflow_backend` is the only deployable**: a thin composition app that pins exact versions
   of every package and mounts their routers. It also runs a **worker** process (same image) for
   background and heavy jobs.
3. **Dependencies point down only:** domains → integration → framework. Domains never import
   each other.
4. **One SQL Server database, one schema and one database login per module.**
5. **"Frozen" is enforced by CI**, not by convention: a release fails if anything a frozen
   module depends on changes, or if a frozen module's own tests fail against it.
6. **Critical rules are enforced in the database** (accounting ledger), so even wrong code
   cannot corrupt them.

---

## 3. Repositories

| Repo | Kind | Depends on | Notes |
|---|---|---|---|
| `deevo_mt_framework_backend` | Platform package (`mtf`) | — | Auth, sessions, tenants, RBAC, audit, reports, txn screens, nav |
| `deevo_integration` | Platform package | `mtf` | Email, WhatsApp, SMS: providers, credentials, templates, retries, delivery status |
| `deevo_crm` | Domain package | `mtf`, `deevo_integration` | |
| `deevo_inventory` | Domain package | `mtf`, `deevo_integration` | |
| `deevo_accounting` | Domain package — **locked** | `mtf`, `deevo_integration` | Strictest change control (§8) |
| `deevo_forecasting` (future) | Domain package | `mtf`, `deevo_integration` | Likely compute-heavy → runs in the worker (§5) |
| `deevoflow_backend` | **Deployable app** | all of the above, exact pins | `main.py`, worker entry point, `uv.lock`; almost no business logic |
| `deevoflow_react` | Frontend | `deevoflow_backend` API | Talks to one URL |

Each package repo contains: `pyproject.toml`, its source package, its own tests (including a
protected `tests/critical/` suite, §9), its migrations for its own schema, and an
`AGENTS.md` / `CLAUDE.md` describing its boundaries for AI tools.

---

## 4. Dependency rules

```
      crm        inventory       accounting       forecasting      ← domains: independent
        \            |               |                /
         \           |               |               /
                       deevo_integration                          ← publishes events, offers send()
                              |
                  deevo_mt_framework_backend (mtf)                ← auth, tenant, RBAC, audit…
```

1. **Domains never import each other.** If a feature needs two domains (e.g. "invoice from a
   CRM deal"), it is wired in `deevoflow_backend` or through events — never by a direct import.
2. **Integration never knows about domains.** It **publishes events** (`message_received`,
   `email_received`, `delivery_failed`, …) and offers `send(...)`. Domains subscribe and call
   it. Integration does not call `crm.create_lead()`.
3. **Events use an outbox table**, written in the same transaction as the change, consumed by
   the worker. Event payloads are a **versioned, documented contract** in `deevo_integration`.
4. **Enforced in CI** with [import-linter](https://github.com/seddonym/import-linter) in
   `deevoflow_backend` (and each package):

```toml
[tool.importlinter]
root_packages = ["crm", "inventory", "accounting", "forecasting", "integration", "mtf"]

[[tool.importlinter.contracts]]
name = "Domains are independent"
type = "independence"
modules = ["crm", "inventory", "accounting", "forecasting"]

[[tool.importlinter.contracts]]
name = "Layers point down"
type = "layers"
layers = ["crm | inventory | accounting | forecasting", "integration", "mtf"]
```

> Note: `mtf` already contains part of an email integration (mailbox models and the Microsoft
> OAuth flow). Decide once whether email belongs in `mtf` or `deevo_integration`, so it is not
> split across both.

---

## 5. Runtime on Azure

```
                Azure Front Door / custom domain  (one public URL)
                                   │
                         deevoflow_backend  (API process)
     mounts: /api/v1/auth, /tenant, /audit, /reports (mtf) · /crm · /inventory · /accounting · …
                                   │
                         deevoflow_backend  (worker process, same image)
     integration sends/receives, outbox consumers, scheduled jobs, forecasting model runs
```

Rules for packages mounted into `deevoflow_backend`:

1. A package contributes **only** its routers (and worker tasks). **No** global middleware,
   no changes to settings, no monkeypatching, no startup hooks that touch shared state.
2. `deevoflow_backend` has a **composed-app snapshot test**: the full list of routes and the
   middleware stack must match an approved snapshot. A package that sneaks in a route or
   middleware fails CI.
3. **Heavy or long-running work never runs in the API process** — it goes to the worker.
   A forecasting job cannot slow down accounting requests.
4. Enabled modules are configurable (`DEEVO_MODULES=crm,inventory,accounting,…`), which keeps
   the upgrade path in §11 open.

---

## 6. Data

| Rule | Detail |
|---|---|
| One database, one schema per module | `crm.*`, `inv.*`, `acct.*`, `fc.*`, `msg.*`, plus mtf's `auth.*`, `tenant.*`, `audit.*`, `rpt.*`, `txn.*`, `nav.*` |
| One database login per module | Each package builds its own SQLAlchemy engine from its own credentials (e.g. `DEEVO_ACCT_DB_USER`), even inside one process |
| Write only your own schema | `acct_app` writes `acct.*` only; nobody else can. A bug elsewhere cannot write to the ledger |
| Read others only through views | Frozen modules publish read contracts (e.g. `crm.v_sales_history`, `inv.v_stock_levels`); new modules get **read-only** grants on those views, never on raw tables |
| Everyone reads auth/tenant | All logins can read `auth.session`, `auth.tenant_user`, `tenant.*` — required by `mtf.get_current_user` |
| No cross-domain foreign keys | Domains reference only mtf's tenant / customer keys |
| Migrations per package | A package migrates only its own schema; DDL runs with the DDL login, never the app login |
| Expand / contract migrations | Add → migrate → remove in a later release, so code can always be rolled back without a database rollback |

---

## 7. Versioning and releases

1. **Semantic versioning** for every package. Breaking changes only in a major version, with a
   deprecation period first.
2. **Packages declare ranges** (`deevo-integration>=1.3,<2`); **`deevoflow_backend` pins exact
   versions with hashes** in `uv.lock`.
3. **Distribution:** start with git tags (`deevo-accounting @ git+https://…/deevo_accounting@v1.0.0`;
   `uv.lock` pins the commit). Move to a private index (Azure Artifacts) when convenient.
4. **Release tags are signed**; protected `main` in every repo; required reviews.
5. **Automated bump PRs** (Renovate or Dependabot) in `deevoflow_backend` — each bump is a normal,
   gated PR.

---

## 8. Freeze policy (accounting, CRM, inventory once in production)

**Definition:** a module is *frozen* when its repo accepts no changes except deliberate,
reviewed releases, and `deevoflow_backend` keeps it on a fixed version.

**What counts as unfreezing** (needs the full process below, reviewed as a change to that module):
- a new version of the module itself;
- any change to a version of something the module depends on — `mtf`, `deevo_integration`,
  or any third-party library in its dependency tree.

**Controls in `deevoflow_backend` CI — a release fails if any check fails:**

| # | Check | Proves |
|---|---|---|
| F1 | **Lock-file check:** compute each frozen module's full dependency tree; fail if any version in it changed in `uv.lock` | Adding/changing another module did not change what the frozen module runs on |
| F2 | **Frozen suites:** install the exact `uv.lock` and run each frozen module's test suite *from its release tag* | Its behaviour is unchanged in the composed app |
| F3 | **Composed-app snapshot** (§5) | No package changed routes or middleware it does not own |
| F4 | **Database grants check:** each module login has exactly its approved grants | Nothing gained write access to a frozen schema |
| F5 | **Deploy record:** image digest + `uv.lock` hash + package versions stored per release | "Accounting has not changed since v1.0.0" is checkable |
| F6 | **Smoke tests per frozen module** after deploying to the staging slot | It works end to end before traffic moves |

**Accounting additionally:**
- Ledger rules enforced **in the database**: every journal entry balances (constraints /
  triggers); ledger tables are **append-only** (UPDATE/DELETE denied, like `audit.audit_log`);
  corrections only via reversing entries.
- AI tools get no write access to `deevo_accounting` by default; it is opened deliberately.

---

## 9. Quality gates for AI-written code

| Gate | Why |
|---|---|
| **Small PRs, one concern each** | A focused diff can be reviewed; a large one cannot |
| **Protected critical tests** (`tests/critical/` under CODEOWNERS): auth, permissions, tenant isolation, money calculations. AI may add tests, not edit these | The typical AI failure is weakening a test so wrong code passes |
| **"Fails before, passes after" evidence** in every PR: new tests must fail on the old code | Proves the tests actually test the change (used for every fix in security.md) |
| **Independent AI review** by a different model/tool (e.g. `/code-review`) | Does not share the author's blind spots |
| **Risk-based human review**: mandatory for accounting, auth/permissions, migrations, money math, settings defaults, and any deleted/loosened test; CI + AI review for the rest | Human attention goes where it matters |

**CI pipeline (required checks on protected `main`, every repo):**
1. lint, type check (pyright/mypy), import-linter
2. secret scan (`gitleaks`), dependency audit (`pip-audit` / `npm audit`), static analysis
   (`semgrep` / `bandit`)
3. unit tests + protected critical tests
4. **authorization matrix**: every endpoint × every role (anonymous, member, admin, portal,
   system) × expected status; a route with no entry fails
5. **API contract diff**: saved `openapi.json` vs new (`oasdiff`); breaking changes fail
6. live-database integration suite (**must be green** — see §12)
7. coverage floor on accounting and auth
8. accounting: golden tests (fixed transactions → exact statements), property-based tests
   (Hypothesis: debits = credits for any input), periodic mutation testing (`mutmut`)

---

## 10. Release and operations

| Area | Practice |
|---|---|
| Staging | Production-like (anonymised) data |
| Deploy | Azure **deployment slot**: deploy to staging slot → smoke tests (F6) → swap |
| Rollback | Swap back (seconds); redeploying a previous release is exact because of pinned versions |
| Feature flags | New behaviour enabled for one internal tenant first, then everyone |
| Monitoring | Alerts on 5xx and on 401/403/429 spikes after a release; unusual audit-log activity (mass updates, permission changes) |
| Accounting checks | Nightly: trial balance = 0, no unbalanced or orphaned entries, reconciliation with source documents; alert on any mismatch |
| Production settings | See the checklist in [security.md](security.md) §1 — the app refuses to start if they are unsafe |

---

## 11. Evolution path

The single `deevoflow_backend` deployment shares one process and one set of library versions
between modules. If a module ever needs **process isolation** (load, failures, or separate
library versions), run the **same image twice** — no code change:

- instance A: `DEEVO_MODULES=accounting`
- instance B: everything else
- Azure Front Door routes `/api/v1/accounting/*` to A, the rest to B; the frontend still sees one URL.

This works because of §5 (packages contribute only routers) and §6 (each module has its own
database login). Splitting a module into its own deployable later is therefore an operations
change, not a rewrite.

Split a module into its own service when it needs: separate library or platform versions from
the others, its own scaling, failure isolation the worker does not give, a separate team or
vendor, or compliance isolation (most likely accounting).

---

## 12. Next steps (in order)

1. **Make the live-database test suite green.** 23 tests fail today on an out-of-date test
   database (security.md §4); while red, new regressions are invisible.
2. **Protected `main` + required CI checks** (§9) in every repo.
3. **`tests/critical/`** protected suite in each repo.
4. **Authorization matrix + OpenAPI contract diff.**
5. **`deevoflow_backend` skeleton:** composition `main.py`, worker, import-linter contracts,
   composed-app snapshot (F3), lock-file check (F1).
6. **Per-module database logins and grants**, starting with accounting (F4).
7. **Staging slot, smoke tests, swap deploys, one-step rollback.**
8. Accounting: database-enforced ledger rules and the nightly checks.
9. Complete the consuming-app tasks in [security.md](security.md) §2 and
   [frontend_security.md](frontend_security.md).

## 13. Open decisions

| Question | Options |
|---|---|
| Where does email integration live? | In `mtf` (where mailbox models already are) or entirely in `deevo_integration` |
| Package distribution | Git tags now vs private index (Azure Artifacts) |
| Forecasting compute | Worker in `deevoflow_backend` vs its own service from day one |
