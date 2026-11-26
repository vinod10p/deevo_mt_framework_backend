# deevo_mt_framework_backend — guide for deevo_api and the deevo_* packages

Audience: developers and AI tools building **`deevo_api`** (the deployable app) and the packages
it mounts (`deevo_integration`, `deevo_crm`, `deevo_workflow`, …).
Companion docs: [architecture.md](architecture.md) (how the repos fit together),
[security.md](security.md) (production settings and security tasks),
[CONVENTIONS.md](CONVENTIONS.md) (coding rules, authoritative), [LAYERING.md](LAYERING.md).

---

## 1. What the framework is

`deevo_mt_framework_backend` is a reusable FastAPI library, package **`mtf`** (Deevo
Multi-Tenant Framework). It provides everything a multi-tenant product needs that is *not*
product logic:

| Area | Package | What it gives you | SQL schema |
|---|---|---|---|
| Authentication | `mtf.auth` | Login, refresh, logout, sessions, users, memberships, login throttling | `auth` |
| Authorization (RBAC v3) | `mtf.auth` | Permissions, roles, role → permission / report grants, `require_permission` | `auth` |
| Tenants | `mtf.tenant` | Tenants, tenant settings, accounts (customers of a tenant), addresses, staff, portal users; Microsoft mailbox connection | `tenant` (+ `email.mailbox*`) |
| Audit | `mtf.audit` | Append-only audit trail, request ids, `audit_insert / update / soft_delete` helpers | `audit` |
| Reports | `mtf.rpt` | Generic report writer: catalog, criteria, lookups, run (stored procs), saved views, actions | `rpt` |
| Transaction screens | `mtf.txn` | Screen metadata (sections, fields, lookups) and `require_screen_permission` | `txn` |
| Navigation | `mtf.nav` | Menu modules and items, filtered by the caller's scope and permissions | `nav` |
| Shared | `mtf.shared` | Settings, DB session, JWT, dependencies, error helpers, client IP | — |

What it does **not** do: product tables or CRUD (leads, messages, workflows, invoices),
dynamic SQL from screen metadata, or Alembic migrations (DDL is applied with SQL scripts in
`sql/` and `docs/*.sql`, run as the DDL login).

### Key concepts

- **Three user scopes** (in every JWT and on every `CurrentUser`):
  - `system` — platform staff (admin app); not tied to a tenant.
  - `tenant` — staff of one tenant (`auth.tenant_user`, role `admin` or member).
  - `tenant_account` — portal user of one account inside a tenant (`auth.tenant_account_user`).
- **Tenant identity always comes from the JWT**, never from the request body or query.
- **Sessions are live.** Every request checks the session in `auth.session` and the user's
  membership, so logout, deactivation and membership removal take effect immediately.
- **IDs** are ULIDs (`VARCHAR(26)`), from `mtf.shared.security.generate_id()`.
- **Soft delete** (`is_deleted`, `deleted_by`) and **`row_version`** optimistic concurrency on
  mutable tables.
- **Errors** are always `{"detail": {"code": "DOMAIN_ENTITY_REASON", "message": "..."}}`.

---

## 2. Installing it

`mtf` is a normal Python package (`deevo-mt-framework-backend`, Python ≥ 3.13, uv). The version
is the release date (e.g. `2026.11.21`).

```bash
# local development — editable, next to deevo_api
uv add --editable ../deevo_mt_framework_backend

# CI / Azure — a tagged or pinned git revision (uv.lock pins the commit)
uv add "deevo-mt-framework-backend @ git+https://github.com/<org>/deevo_mt_framework_backend@<tag-or-commit>"
```

Packages (`deevo_crm`, …) declare `mtf` as a dependency with a range; **`deevo_api` pins the
exact version** in `uv.lock` (see [architecture.md](architecture.md) §7).

Requirements: ODBC Driver 17 or 18 for SQL Server, and a database with the framework schemas
applied (`auth`, `tenant`, `audit`, `rpt`, `txn`, `nav` — DDL in `sql/` and `docs/`).

---

## 3. Mounting it in deevo_api

The framework's own `main.py` is a development server only. `deevo_api` builds its own app and
mounts the routers. **Use the same URL prefixes `deevoflow_backend` uses today** so the
frontend does not change — check them in the Phase 0 route list; products have used `/api/v1`.

```python
# deevo_api/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mtf.audit.api import router as mtf_audit_router
from mtf.audit.middleware import AuditRequestIdMiddleware
from mtf.auth.api import router as mtf_auth_router
from mtf.nav.api import router as mtf_nav_router
from mtf.rpt.api import router as mtf_rpt_router
from mtf.shared.config import get_settings
from mtf.tenant.api import router as mtf_tenant_router
from mtf.tenant.api.tenant import mailbox_oauth_callback
from mtf.tenant.api.tenant_account_portal import router as mtf_portal_router
from mtf.txn.api import router as mtf_txn_router

settings = get_settings()  # validates production settings at startup (see §8)

app = FastAPI(title="Deevo API", version=settings.app_version, debug=settings.debug)

# Middleware lives ONLY in deevo_api, never in a package.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)
app.add_middleware(AuditRequestIdMiddleware)  # request id on every audit row


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


API = "/api/v1"  # match today's deevoflow_backend prefix
app.include_router(mtf_auth_router, prefix=f"{API}/auth")
app.include_router(mtf_tenant_router, prefix=f"{API}/tenant")
app.include_router(mtf_portal_router, prefix=f"{API}/account")
app.include_router(mtf_audit_router, prefix=f"{API}/audit")
app.include_router(mtf_rpt_router, prefix=API)   # → {API}/reports/...
app.include_router(mtf_txn_router, prefix=API)   # → {API}/screens/...
app.include_router(mtf_nav_router, prefix=API)   # → {API}/nav/...

# Microsoft mailbox OAuth callback: the URL must equal DEEVO_MICROSOFT_REDIRECT_URI and
# the redirect URI registered in Microsoft Entra.
app.get(f"{API}/mailboxes/callback")(mailbox_oauth_callback)

# Then the packages, from deevo_api/modules.py filtered by DEEVO_MODULES:
# for prefix, router in deevo_crm.module.routers(): app.include_router(router, prefix=prefix)
```

### Routes the framework adds (relative to the prefixes above)

| Router | Main routes | Who |
|---|---|---|
| auth | `POST /login`, `POST /refresh`, `POST /logout`, `POST /logout-all`, `GET /me` | public (login, refresh) / any logged-in user |
| auth (browser) | `POST /browser/login`, `/browser/refresh`, `/browser/logout` — refresh token kept in an `HttpOnly`, `Secure`, `SameSite=Strict` `__Host-` cookie per frontend origin | tenant and portal users, from an allowed origin only |
| auth (admin) | `/users`, `/tenant-users`, `/permissions`, `/roles`, `/roles/{id}/permissions`, `/roles/{id}/default-reports` | system |
| tenant (tenant staff) | `GET /me`, `/users`, `/roles`, `/permissions`, `/reports`, `/users/{id}/roles`, `/accounts`, `/accounts/{id}/users`, `/accounts/{id}/addresses` | tenant (admins for management) |
| tenant (system) | `/`, `/{tenant_id}`, `/{tenant_id}/users`, `/{tenant_id}/accounts…`, `/{tenant_id}/mailboxes`, `/{tenant_id}/mailboxes/{id}/authorize` | system |
| tenant (public) | `GET /by-subdomain?subdomain=`, `GET /by-id?tenant_id=` — tenant name for login pages | **no login** |
| account (portal) | `/users`, `/users/{id}` | portal account admins |
| audit | `GET /logs`, `GET /logs/{id}` | system, tenant admins, account admins |
| reports | `GET /reports`, `GET /reports/{key}`, `…/lookups/{criteria}`, `POST …/run`, `…/views`, `POST …/actions/{action}/resolve` | tenant and portal users with the report granted |
| screens | `GET /screens/{screen_key}` | logged-in users of a tenant |
| nav | `GET /nav/modules`, `GET /nav/modules/{code}/items` | any logged-in user (filtered) |

**Public routes (no login):** `/health`, `auth/login`, `auth/refresh`, `auth/browser/*`
(origin-checked), `tenant/by-subdomain`, `tenant/by-id`, and the mailbox callback (protected by
the signed `state`). Everything else needs a valid Bearer token.

The full list is in `/openapi.json` of the running app. Snapshot it in `deevo_api`'s tests so an
upgrade that changes routes is noticed ([architecture.md](architecture.md) §5).

---

## 4. Protecting your own routes

Import from `mtf.shared.deps`. **Every protected route in every package must depend on these**
— never decode JWTs yourself (see [security.md](security.md) §2.2 B6/B7).

| Dependency | Gives | Rejects |
|---|---|---|
| `get_current_user` | `CurrentUser(user_id, user_type, user_scope, tenant_id, account_id)` | 401 — bad/expired token, wrong token type, revoked session, inactive user or membership |
| `require_scope("tenant")` / `"system"` / `"tenant_account"` | `CurrentUser` | 403 if another scope |
| `require_any_scope("tenant", "tenant_account")` | `CurrentUser` | 403 |
| `get_tenant_id` | tenant id from the JWT (tenant staff) | 403 |
| `get_tenant_id_portal`, `get_account_id` | tenant / account id from the JWT (portal users) | 403 |
| `require_tenant_role("admin")` | `CurrentUser` with an active membership in that role | 403 |
| `require_portal_account_admin()` | portal user who is admin of their account | 403 |
| `require_permission("crm.lead.edit")` | `CurrentUser` holding that RBAC permission | 403 `AUTH_FORBIDDEN` (does not check scope — add `require_scope` too) |
| `mtf.txn.api.deps.require_screen_permission("lead", "edit")` | effective screen permissions | 403 — uses RBAC `screen.lead.edit` when the tenant has `rbac.screens=on`, else `txn.screen_permission` |
| `get_db` | SQLAlchemy `Session` (rolled back on error, always closed) | — |
| `get_pagination` | `PaginationParams(skip, limit)`, limit ≤ 200 | 422 |

Example — a CRM route:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mtf.shared.deps import CurrentUser, get_db, get_pagination, PaginationParams, require_scope
from mtf.txn.api.deps import require_screen_permission

router = APIRouter(prefix="/leads", tags=["crm"])


@router.get("")
def list_leads(
    user: CurrentUser = Depends(require_scope("tenant")),
    _perm=Depends(require_screen_permission("lead", "view")),
    page: PaginationParams = Depends(get_pagination),
    db: Session = Depends(get_db),
):
    # ALWAYS filter by user.tenant_id — never by a tenant id from the request.
    return lead_service.list(db, tenant_id=user.tenant_id, skip=page.skip, limit=page.limit)
```

Permission codes must exist in `auth.permission` (seed them with SQL, e.g.
`sql/auth_rbac_seed_tenant_catalog_v1.sql` style) and be granted to roles; otherwise nobody
passes the check.

---

## 5. Writing data: errors, audit, IDs

**Errors** — `mtf.shared.exceptions` (each raises `HTTPException` with the standard body):

```python
from mtf.shared.exceptions import not_found, conflict, forbidden, bad_request, row_version_conflict

not_found("CRM_LEAD", "Lead not found")      # 404 {"code": "CRM_LEAD_NOT_FOUND", ...}
conflict("CRM_LEAD", "Email already used")   # 409 CRM_LEAD_CONFLICT
row_version_conflict("CRM_LEAD")             # 409 — stale row_version
```

**Audit** — write an audit row in the **same transaction** as the change:

```python
from mtf.audit.api.deps import get_audit_source          # FastAPI dependency → AuditSource
from mtf.audit.service import audit_insert, audit_update, audit_soft_delete, row_snapshot

before = row_snapshot(lead)
lead.status = "won"
audit_update(db, entity=lead, schema_name="crm", table_name="lead",
             before=before, actor=user, source=source)
db.commit()
```

`AuditSource` carries the client IP (proxy-aware, see `DEEVO_TRUSTED_PROXIES`), user agent,
request id and session id. Secrets are stripped from snapshots automatically.

**IDs and passwords** — `generate_id()` for new rows; never hash or verify passwords outside
`mtf.auth`.

**Database session** — `get_db` uses one shared engine (`mtf.shared.database.engine`, login
`DEEVO_MSSQL_USER`, pool 10 + 20 overflow). During the cutover packages may use it as-is. When
per-module logins are introduced ([architecture.md](architecture.md) §6), each package builds
its own engine from `get_settings().sqlalchemy_database_uri()`-style settings with its own
credentials, so the production TLS rules still apply.

**Models** — give each package its **own** `DeclarativeBase`; do not add tables to
`mtf.shared.database.Base`. Reference framework rows (tenant, account, user) by id columns;
do not write to `auth.*`, `tenant.*`, `audit.*`, `rpt.*`, `txn.*` or `nav.*` directly — use the
framework API or the documented seed scripts.

---

## 6. Reports, screens and menus (metadata-driven UI)

The frontend renders reports, transaction screens and menus from metadata the framework
serves. A product feature typically adds **rows and stored procedures**, not Python:

| Feature | What the product adds | Guide |
|---|---|---|
| A list / report page | `rpt.report_definition` + columns + criteria rows, a stored procedure that returns the rows (reads `SESSION_CONTEXT` tenant/user), lookup procs, role grants | `prompts/rpt/NEW_REPORT_PROMPT.md`, [REPORTING_FRAMEWORK_CONTEXT.md](REPORTING_FRAMEWORK_CONTEXT.md) |
| Report → screen buttons | `rpt.report_action` / `report_action_param` rows | `prompts/txn/DEEVOFLOW_LEAD_REPORT_ACTIONS.md` |
| A create/edit screen | `txn.screen`, sections, fields, lookups; **the CRUD endpoints themselves are product code**, gated by `require_screen_permission` | `prompts/txn/DEEVOFLOW_LEAD_SCREEN.md` |
| A menu entry | `nav.menu_module` / `nav.menu_item` rows, tied to a permission or report | `sql/nav_menu_seed_v1.sql`, `prompts/nav/NAV_FRONTEND_PROMPT.md` |

Report procedures run on a connection whose `SESSION_CONTEXT` holds the caller's tenant and
user (`mtf.rpt.execution.connection`), with bound parameters and a statement timeout
(`DEEVO_REPORT_QUERY_TIMEOUT_SECONDS`). Procs must filter by that tenant.

---

## 7. Mailbox (Microsoft 365) connection

`mtf.tenant` owns mailbox records (`email.mailbox`, `email.mailbox_credential`) and the OAuth
connect flow:

1. The admin app (system user) calls `GET …/tenant/{tenant_id}/mailboxes/{mailbox_id}/authorize`
   and receives `{"authorization_url": ...}`; it opens that URL in the browser.
2. Microsoft redirects to the callback (`…/mailboxes/callback`), which checks the signed
   `state`, exchanges the code, verifies the account can open that mailbox, stores the tokens,
   then redirects to `DEEVO_MAILBOX_OAUTH_SUCCESS_URL`.

Reading and sending mail is product code (`deevo_integration`), which reads the stored
credentials. Where email ownership finally sits is an open decision
([architecture.md](architecture.md) §14).

---

## 8. Configuration

All settings are `DEEVO_*` environment variables read by `mtf.shared.config.get_settings()`
(cached; documented in `.env.example`). `deevo_api` reads the same variables — **set them once
in the Azure app settings**.

| Group | Settings |
|---|---|
| App | `DEEVO_ENVIRONMENT` (`development` / `staging` / `production`), `DEEVO_DEBUG` |
| Database | `DEEVO_MSSQL_SERVER`, `_PORT`, `_DATABASE`, `_USER`, `_PASSWORD`, `_ODBC_DRIVER`, `_ENCRYPT`, `_TRUST_SERVER_CERTIFICATE` (or `DEEVO_DATABASE_URL`) |
| JWT | `DEEVO_JWT_SECRET_KEY`, `DEEVO_JWT_ALGORITHM`, `DEEVO_JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `DEEVO_JWT_REFRESH_TOKEN_EXPIRE_DAYS` |
| CORS | `DEEVO_ALLOWED_ORIGINS` (JSON list), `DEEVO_CORS_ALLOW_CREDENTIALS` |
| Proxy / client IP | `DEEVO_TRUSTED_PROXIES` (JSON list of IPs/CIDRs — set this behind Front Door / App Gateway) |
| Login throttling | `DEEVO_LOGIN_MAX_FAILURES_PER_IP`, `…_PER_ACCOUNT_IP`, `DEEVO_LOGIN_FAILURE_WINDOW_SECONDS`, `DEEVO_LOGIN_ACCOUNT_LOCKOUT_*` |
| Reports | `DEEVO_REPORT_QUERY_TIMEOUT_SECONDS` |
| Microsoft | `DEEVO_MICROSOFT_CLIENT_ID`, `_CLIENT_SECRET`, `_AUTHORITY`, `_REDIRECT_URI`, `DEEVO_MAILBOX_OAUTH_SUCCESS_URL` |

**With `DEEVO_ENVIRONMENT=production` the app refuses to start** if the JWT secret is weak or a
placeholder, the database connection is not encrypted and certificate-verified, an origin is not
`https://`, or the mailbox success URL is not `https://`. The full checklist is
[security.md](security.md) §1. Package-specific settings use their own prefix
(`DEEVO_CRM_*`, …) in the package's own `Settings` class.

**CORS credentials:** keep `DEEVO_CORS_ALLOW_CREDENTIALS=true` if the frontend uses the
`/auth/browser/*` endpoints (they set the refresh cookie). It can be `false` only if every
frontend uses Bearer tokens alone.

---

## 9. Testing with the framework

- **Unit tests:** override dependencies instead of creating tokens:

  ```python
  from mtf.shared.deps import CurrentUser, get_current_user

  app.dependency_overrides[get_current_user] = lambda: CurrentUser(
      user_id="01H...", user_type="app_user", user_scope="tenant", tenant_id="01H...")
  ```

  Note `require_scope`, `require_permission` and `require_screen_permission` sit on top of
  `get_current_user`; override the specific checker if a test must bypass a DB lookup.
- **Integration tests:** log in through `POST …/auth/login` with seeded users; never build
  JWTs by hand (tokens without a live session are rejected).
- **Throttle reset:** the login throttle is per process and TestClient requests all come from
  `testclient`. Add to `tests/conftest.py`:

  ```python
  @pytest.fixture(autouse=True)
  def reset_login_throttle():
      from mtf.auth.services.login_throttle import login_throttle
      login_throttle.clear()
      yield
      login_throttle.clear()
  ```
- `DEEVO_SKIP_DB_TESTS=1` / `pytest -m "not integration"` skips tests that need SQL Server.

---

## 10. Rules for packages (summary)

| Do | Don't |
|---|---|
| Depend on `mtf.shared.deps` for every protected route | Decode or create JWTs, or import `jose` |
| Take tenant/account from `CurrentUser` | Accept `tenant_id` from the body or query for scoping |
| Write audit rows with `audit_*` in the same transaction | Write to `audit.*` or other framework tables directly |
| Raise errors with `mtf.shared.exceptions` | Return ad-hoc error shapes |
| Use your own `DeclarativeBase` and schema | Add models to `mtf`'s `Base` or other packages' schemas |
| Seed reports/screens/menus/permissions with SQL scripts in your repo | Add product logic or generic services to `mtf` |
| Ask for framework changes in writing (framework repo) | Patch or monkeypatch `mtf` from a package |
| Leave middleware and CORS to `deevo_api` | Add middleware or startup hooks in a package |

---

## 11. Upgrading the framework in deevo_api

1. Read the framework's release notes / `docs/security.md` for behaviour changes.
2. Bump the pin in `deevo_api` (`uv lock --upgrade-package deevo-mt-framework-backend`).
3. CI must pass: route/OpenAPI snapshot, import rules, all package suites, frozen-module checks
   ([architecture.md](architecture.md) §8).
4. Deploy to the staging slot, smoke-test login, refresh, a report run and a screen, then swap.
