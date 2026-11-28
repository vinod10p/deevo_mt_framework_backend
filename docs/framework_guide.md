# mtf — how to use the framework in a backend application

Audience: developers and AI tools building **any backend application** on top of
`deevo_mt_framework_backend` (Python package **`mtf`**). The application that runs the web
server is called the **host** below. It may also mount **product packages**, its own Python
packages holding product features.

Hand this document to the host's developer or AI tool: it explains what the framework gives,
how to install and mount it, and the rules a host must follow.

Companion docs: [CONVENTIONS.md](CONVENTIONS.md) (coding rules, authoritative),
[security.md](security.md) (production settings), [LAYERING.md](LAYERING.md),
[architecture.md](architecture.md) (how the Deevo repos fit together),
[`../sql/business_unit_database_design.md`](../sql/business_unit_database_design.md)
(business units: design and tables).

---

## 1. What the framework is

`mtf` (Multi-Tenant Framework) is a reusable FastAPI + SQLAlchemy library for SQL Server. It
provides what every multi-tenant product needs that is **not** product logic:

| Area | Package | What it gives you | SQL schema |
|---|---|---|---|
| Authentication | `mtf.auth` | Login, refresh, logout, live sessions, users, memberships, login throttling | `auth` |
| Authorization (RBAC) | `mtf.auth` | Permissions, roles, role → permission and report grants, `require_permission` | `auth` |
| Tenants and business units | `mtf.tenant` | Tenants (companies), **business units** (stores), settings, accounts (a tenant's customers), addresses, staff, portal users, Microsoft mailbox connection | `tenant` (+ `email.mailbox*`) |
| Audit | `mtf.audit` | Append-only audit trail, request ids, `audit_insert` / `audit_update` / `audit_soft_delete` | `audit` |
| Reports | `mtf.rpt` | Generic report writer: catalog, criteria, lookups, run (stored procedures), saved views, actions | `rpt` |
| Transaction screens | `mtf.txn` | Screen metadata (sections, fields, lookups) and `require_screen_permission` | `txn` |
| Navigation | `mtf.nav` | Menu modules and items, filtered by the caller's scope and permissions | `nav` |
| Shared | `mtf.shared` | Settings, database session, JWT, dependencies, error helpers, model mixins, clock | — |

It does **not** contain product tables or CRUD (orders, leads, stock, invoices …), build SQL from
screen metadata, or run Alembic migrations. Database DDL is applied with SQL scripts (§3).

### Key concepts

- **Tenant** — one customer company of your product (e.g. *London Jeweler*). It is the isolation
  boundary: no data crosses tenants.
- **Business unit** — a place inside a tenant: its stores, a warehouse, a workshop, an online
  shop. Every tenant has:
  - exactly **one root unit** (`bu_type = 'root'`, code `COMPANY`, named after the tenant), which
    owns tenant-wide data and stands for "All stores";
  - **at least one store** (the first is `MAIN`). A single-store tenant simply has root + `MAIN`.
- **Three user scopes**, in every token and every `CurrentUser`:
  - `system` — platform staff (your admin app); not tied to a tenant; no business unit.
  - `tenant` — staff of one tenant (`auth.tenant_user`, role `admin` or `member`). Staff log in
    **at a store** and can switch store.
  - `tenant_account` — portal user of one account of a tenant (`auth.tenant_account_user`).
    Portal sessions always sit at the tenant's root unit.
- **Tenant and store come from the login, never from the request.** The tenant is in the
  signed access token, checked against the live session; the store is read from the session
  row. Never take either from the request body or query.
- **Sessions are live.** Every request checks the session row (`auth.session`) and the user's
  membership, so logout, deactivation, membership removal and lost store access take effect at
  once.
- **Permissions follow the store.** A staff user's effective roles are the roles held at the
  root (they apply in every store) plus the roles held at the session's store.
- **IDs** are ULIDs (`VARCHAR(26)`) from `mtf.shared.security.generate_id()`.
- **Soft delete** (`is_deleted`, `deleted_at`, `deleted_by`) and **`row_version`** optimistic
  concurrency on mutable tables.
- **Errors** are always `{"detail": {"code": "DOMAIN_ENTITY_REASON", "message": "..."}}`.

---

## 2. Installing

`mtf` is a normal Python package: distribution `deevo-mt-framework-backend`, Python ≥ 3.13,
managed with uv. The version is the release date (e.g. `2026.11.22`).

```bash
# local development — editable, next to your host repo
uv add --editable ../deevo_mt_framework_backend

# CI / deployment — a pinned git revision (uv.lock pins the commit)
uv add "deevo-mt-framework-backend @ git+https://github.com/<org>/deevo_mt_framework_backend@<tag-or-commit>"
```

Product packages declare `mtf` with a version range; **the host pins the exact version** in its
lock file.

Requirements: Microsoft ODBC Driver 17 or 18 for SQL Server, and a SQL Server database with the
framework schemas (§3).

---

## 3. Database

The framework owns six schemas: `auth`, `tenant`, `audit`, `rpt`, `txn`, `nav`, plus
`email.mailbox` / `email.mailbox_credential` if you use the mailbox connection. Your product
tables go in **your own schemas**.

| What | Where |
|---|---|
| Table DDL | The **reference database is `deevo_app_dev3`**, which has business units. The scripts in `sql/` (`auth_rbac_schema_v3.sql`, `rpt_schema_v5.sql`, `txn_schema_v2.sql`, `nav_menu_schema_v1.sql`, `audit_schema_v2.sql`, `database_schema_v1.sql`) are the pre-business-unit baseline and **lack `tenant.business_unit` and the `business_unit_id` columns**. Until consolidated scripts exist, create a new database from `deevo_app_dev3` (SSMS → Generate Scripts → schema only) |
| Seed data (permissions, platform roles, menus, sample reports) | `sql/auth_rbac_seed_v3.sql`, `sql/auth_rbac_seed_tenant_catalog_v1.sql`, `sql/nav_menu_seed_v1.sql`, `sql/rpt_seed_sample_report.sql`, then the `rbac_fix_*` / `nav_menu_fix_*` scripts in number order |
| Business-unit scripts | `sql/dev3_10_business_unit_defaults.sql` (root + `MAIN` for existing tenants), `dev3_11_rpt_procedures.sql` (report procedures), `dev3_12_move_custom_roles_to_store.sql` (one-time data fix), `dev3_13_integrity_triggers.sql` (integrity triggers) |

Run DDL as the database owner login; the application connects with a restricted login
(`DEEVO_MSSQL_USER`). The audit log is append-only for that login.

New tenants need no script: `POST /tenant/` (onboarding) creates the tenant, its root unit and
`MAIN` in one transaction.

---

## 4. Mounting it in the host

The framework's own `main.py` is a development server only. The host builds its own FastAPI app
and mounts the routers. **Pick one prefix (`API` below) and keep it stable**: the frontend calls
these URLs.

```python
# host/main.py
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

settings = get_settings()  # validates production settings at startup (see §11)

app = FastAPI(title="My API", version=settings.app_version, debug=settings.debug)

# Middleware lives ONLY in the host, never in a package.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],  # lets browsers read the wait time on a 429 login
)
app.add_middleware(AuditRequestIdMiddleware)  # request id on every audit row


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


API = "/api/v1"
app.include_router(mtf_auth_router, prefix=f"{API}/auth")
app.include_router(mtf_tenant_router, prefix=f"{API}/tenant")
app.include_router(mtf_portal_router, prefix=f"{API}/account")
app.include_router(mtf_audit_router, prefix=f"{API}/audit")
app.include_router(mtf_rpt_router, prefix=API)   # → {API}/reports/...
app.include_router(mtf_txn_router, prefix=API)   # → {API}/screens/...
app.include_router(mtf_nav_router, prefix=API)   # → {API}/nav/...

# Only if you use the Microsoft mailbox connection (§10). The URL must equal
# DEEVO_MICROSOFT_REDIRECT_URI. (The tenant router also serves {API}/tenant/mailboxes/callback.)
app.get(f"{API}/mailboxes/callback")(mailbox_oauth_callback)

# Then your own routers and product packages:
# app.include_router(orders_router, prefix=f"{API}/orders")
```

Mount the framework routers **as they are**. Do not wrap or proxy them, copy their response
models, or re-implement login: new fields and routes then reach your frontend with no host
change.

### Routes the framework adds (relative to the prefixes above)

| Router | Main routes | Who |
|---|---|---|
| auth | `POST /login`, `POST /refresh`, `POST /logout`, `POST /logout-all`, `GET /me` | public (login, refresh) / any logged-in user |
| auth (store) | `POST /session/business-unit` — switch the session's store | tenant staff |
| auth (browser) | `POST /browser/login`, `/browser/refresh`, `/browser/logout`, `/browser/session/business-unit` — the refresh token lives in an `HttpOnly`, `Secure`, `SameSite=Strict` `__Host-` cookie per frontend origin | tenant and portal users, from an allowed origin only |
| auth (admin) | `/users`, `/tenant-users`, `/permissions`, `/roles`, `/roles/{id}/permissions`, `/roles/{id}/default-reports` | system |
| tenant (tenant staff) | `GET /me`, `/users`, `/roles`, `/roles/{id}/permissions`, `/roles/{id}/reports`, `/permissions`, `/reports`, `/users/{id}/roles`, `/accounts`, `/accounts/{id}/users`, `/accounts/{id}/addresses` | tenant (admins for management) |
| tenant (system) | `/`, `/{tenant_id}`, `/{tenant_id}/users`, `/{tenant_id}/accounts…`, `/{tenant_id}/mailboxes`, `/{tenant_id}/mailboxes/{id}/authorize` | system |
| tenant (public) | `GET /by-subdomain?subdomain=`, `GET /by-id?tenant_id=` — tenant name for login pages | **no login** |
| account (portal) | `/users`, `/users/{id}` | portal account admins |
| audit | `GET /logs`, `GET /logs/{id}` | system, tenant admins, account admins |
| reports | `GET /reports`, `GET /reports/{key}`, `…/lookups/{criteria}`, `POST …/run`, `…/views`, `…/views/default`, `POST …/actions/{action}/resolve` | tenant and portal users with the report granted |
| screens | `GET /screens/{screen_key}` | logged-in users of a tenant |
| nav | `GET /nav/modules`, `GET /nav/modules/{code}/items` | any logged-in user (filtered) |

**Public routes (no login):** `/health`, `auth/login`, `auth/refresh`, `auth/browser/login` and
`/browser/refresh` (origin-checked), `tenant/by-subdomain`, `tenant/by-id`, and the mailbox
callback (protected by a signed `state`). Everything else needs a valid Bearer token.

The full list is the running app's `/openapi.json`. Snapshot it in the host's tests so an
upgrade that changes routes is noticed.

---

## 5. Login, sessions and stores

| Caller | Login body (`POST {API}/auth/login` or `/auth/browser/login`) |
|---|---|
| Tenant staff | `email`, `password`, `tenant_id`, `business_unit_code` (**required**), `created_from` |
| Portal user | `email`, `password`, `tenant_id`, `created_from` (a store is ignored) |
| System user | `email`, `password`, `created_from` |

- `tenant_id`: login pages resolve the typed company with `GET {API}/tenant/by-subdomain`.
- `created_from`: `web`, `desktop`, `mobile_ios`, `mobile_android` or `api`.

**Store rules for staff:**

- **Matching:** the code is matched trimmed and case-insensitive within the tenant.
- **Which stores a user may open:**
  - a role at the root: any active store, or the root code (`COMPANY` = "All stores" mode);
  - roles at particular stores: those stores only;
  - a member with no roles: their default store, else `MAIN`.
- **Failures:** every store failure answers `401 AUTH_UNAUTHORIZED` "You don't have access to
  this store"; a missing store answers "Store is required". A wrong store does not count toward
  the login lockout.

**Responses** (login, refresh and switch) carry, besides the tokens, `user_scope`, `tenant_id`,
`business_unit_id`, `business_unit_code`, `business_unit_name`, `business_unit_type`
(`root` / `store`) and `multi_store` (the tenant has more than one active store).

**Switching store:** `POST {API}/auth/session/business-unit` with
`{"business_unit_code": "MAYFAIR"}`, staff only.

- It uses the same rules as login and returns a **new access and refresh token**; the old ones
  stop working at once.
- A refused switch is a `401` with the store message and leaves the session unchanged, so
  clients must not treat it as an expired session.
- The browser variant puts the new refresh token in the cookie.

**Refresh** re-checks the store. If it was closed or the user lost access, the session ends
(`401`).

**`GET {API}/auth/me`** returns the profile, `permissions`, `reports`, `business_unit`,
`multi_store` and `business_units` (the stores the user may switch to).

Permission codes are never in the token or the login response; read them from `/auth/me`.

---

## 6. Protecting your own routes

Import from `mtf.shared.deps`. **Every protected route must depend on these**; never decode
tokens yourself.

| Dependency | Gives | Rejects |
|---|---|---|
| `get_current_user` | `CurrentUser(user_id, user_type, user_scope, tenant_id, account_id, business_unit_id)`; the unit is read from the session row | 401 — bad or expired token, wrong token type, revoked session, inactive user or membership |
| `require_scope("tenant")` / `"system"` / `"tenant_account"` | `CurrentUser` | 403 for another scope |
| `require_any_scope("tenant", "tenant_account")` | `CurrentUser` | 403 |
| `get_tenant_id` | tenant id from the access token (tenant staff) | 403 |
| `get_business_unit_id` | the session's business unit (tenant staff) | 401 if the session has none |
| `get_tenant_id_portal`, `get_account_id` | tenant / account id (portal users) | 403 |
| `require_tenant_role("admin")` | `CurrentUser` with an active membership in that role | 403 |
| `require_portal_account_admin()` | portal user who is admin of their account | 403 |
| `require_permission("orders.order.edit")` | `CurrentUser` holding that permission **in the session's store** | 403 `AUTH_FORBIDDEN`; does not check scope, so add `require_scope` too |
| `mtf.txn.api.deps.require_screen_permission("order", "edit")` | effective screen permissions | 403 — uses RBAC `screen.order.edit` when the tenant has `rbac.screens=on`, else `txn.screen_permission` |
| `get_permission_resolver` | the request's `PermissionResolver` (`permission_codes`, `has_permission`, `report_grants`) | — |
| `get_db` | SQLAlchemy `Session` (rolled back on error, always closed) | — |
| `get_pagination` | `PaginationParams(skip, limit)`, limit ≤ 200 | 422 |

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mtf.shared.deps import (
    CurrentUser, PaginationParams, get_business_unit_id, get_db, get_pagination,
    require_permission, require_scope,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("")
def list_orders(
    user: CurrentUser = Depends(require_scope("tenant")),
    _perm: CurrentUser = Depends(require_permission("orders.order.view")),
    store_id: str = Depends(get_business_unit_id),
    page: PaginationParams = Depends(get_pagination),
    db: Session = Depends(get_db),
):
    # ALWAYS filter by the session's tenant (and store) — never by ids from the request.
    return order_service.list(
        db, tenant_id=user.tenant_id, business_unit_id=store_id,
        skip=page.skip, limit=page.limit,
    )
```

Permission codes must exist in `auth.permission` (seed them with SQL) and be granted to roles;
otherwise nobody passes the check. Assign roles with
`POST {API}/tenant/users/{id}/roles`:
- pass `business_unit_id` to hold the role at one store;
- leave it out to use the user's default store;
- the root is allowed only for tenant-wide roles.

If you call `PermissionResolver` yourself, pass `CurrentUser` (or an object with the same
fields, including `business_unit_id`).

---

## 7. Business units in your own tables

Give **every product table that holds tenant data** both `tenant_id` and `business_unit_id`
(`VARCHAR(26) NOT NULL`). Decide per table whether it is **shared** or **owned**:

| Kind | Examples | Rows live at | Read filter | Write rule |
|---|---|---|---|---|
| **shared** | products, customers, price lists, settings | the root (sometimes a store override) | `business_unit_id IN (:store, :root)`; on the same key, the store's row wins | tenant-wide rows at the root |
| **owned** | sales, stock, cash, transfers, repairs | a store | `business_unit_id = :store` | only at a store, **never at the root** |

**DDL** — the same-tenant rule is a composite foreign key, enforced by the database:

```sql
business_unit_id varchar(26) NOT NULL,
CONSTRAINT FK_order_business_unit FOREIGN KEY (business_unit_id, tenant_id)
    REFERENCES tenant.business_unit (id, tenant_id),
```

Put `tenant_id, business_unit_id` first in your indexes. Tenant-wide codes (SKU, customer code)
stay unique per tenant, **without** `business_unit_id`, so two stores can't create the same one.

**Models** — use your own `DeclarativeBase` and map the two columns. Keep the composite FK in the
DDL: an ORM `ForeignKeyConstraint` to `tenant.business_unit` only resolves inside `mtf`'s own
metadata. You may reuse the column helpers and mixins from `mtf.shared.model_columns`:
- `ulid()`, `ulid_pk()`, `flag()`, `utc_timestamp()`;
- `StandardColumnsMixin`, which gives `Model.new(by=…, **values)` and `row.mark_deleted(by)`.

**Values to use:**

| Need | Call |
|---|---|
| The session's store | `Depends(get_business_unit_id)` or `user.business_unit_id` |
| The tenant's root unit | `mtf.tenant.business_units.root_unit_id(db, tenant_id)` (cached) |
| Is the session in "All stores" mode? | `user.business_unit_id == root_unit_id(db, user.tenant_id)` → refuse writes to owned tables |
| Unit details, lists, access checks | `mtf.tenant.services.business_unit_service.BusinessUnitService(db)` — `get_root`, `get_active`, `get_active_by_code`, `list_active`, `list_open_to_staff`, `is_multi_store`, `allowed_units_for_staff` |

The framework does not yet add these filters for you; a shared repository mixin
(`TenantBUMixin`) is planned. Until then, **every query on a tenant table filters by `tenant_id`
and by the business-unit rule above**, in the service layer.

---

## 8. Writing data: errors, audit, ids

**Errors** — `mtf.shared.exceptions`. Each raises `HTTPException` with the standard body:

```python
from mtf.shared.exceptions import (
    bad_request, conflict, forbidden, not_found, row_version_conflict, unauthorized,
)

not_found("ORDERS_ORDER", "Order not found")    # 404 {"code": "ORDERS_ORDER_NOT_FOUND", ...}
conflict("ORDERS_ORDER", "Number already used")  # 409 ORDERS_ORDER_CONFLICT
row_version_conflict("ORDERS_ORDER")             # 409 — stale row_version
```

**Audit** — write the audit row in the **same transaction** as the change:

```python
from mtf.audit.api.deps import get_audit_source  # FastAPI dependency → AuditSource
from mtf.audit.service import audit_insert, audit_soft_delete, audit_update, row_snapshot

before = row_snapshot(order)
order.status = "paid"
audit_update(db, entity=order, schema_name="orders", table_name="order",
             before=before, actor=user, source=source)
db.commit()
```

- The audit row takes its `tenant_id` and `business_unit_id` from the actor (the session's
  store), or the tenant's root when there is no session.
- `AuditSource` carries the client IP (proxy-aware, see `DEEVO_TRUSTED_PROXIES`), user agent,
  request id and session id.
- Secrets are stripped from snapshots automatically.

**IDs, time, passwords:**
- new rows use `generate_id()` (or `Model.new(by=…)`);
- UTC timestamps use `mtf.shared.clock.utc_now()`;
- never hash or verify passwords outside `mtf.auth`.

**Soft delete:** set `is_deleted`, `deleted_at` **and** `deleted_by` together; the database
rejects a partial delete. `row.mark_deleted(by)` does all three.

**Database session:** `get_db` uses one shared engine (`mtf.shared.database.engine`, login
`DEEVO_MSSQL_USER`). If a package later needs its own database login, it builds its own engine
from its own settings, keeping the production TLS rules.

**Framework tables are the framework's.** Reference tenants, units, accounts and users by id
columns. Do not insert into or update `auth.*`, `tenant.*`, `audit.*`, `rpt.*`, `txn.*` or
`nav.*` directly; use the framework's API and services or its seed scripts. dev3 rejects rows
without a valid `business_unit_id`.

---

## 9. Reports, screens and menus (metadata-driven UI)

The frontend renders reports, transaction screens and menus from metadata the framework serves.
A product feature usually adds **rows and stored procedures**, not Python:

| Feature | What the product adds | Guide |
|---|---|---|
| A list / report page | `rpt.report_definition` + columns + criteria rows, a stored procedure returning the rows, lookup procedures, role grants | `prompts/rpt/NEW_REPORT_PROMPT.md`, [REPORTING_FRAMEWORK_CONTEXT.md](REPORTING_FRAMEWORK_CONTEXT.md) |
| Report → screen buttons | `rpt.report_action` / `report_action_param` rows | `prompts/txn/DEEVOFLOW_LEAD_REPORT_ACTIONS.md` |
| A create / edit screen | `txn.screen`, sections, fields, lookups; **the CRUD endpoints are product code**, gated by `require_screen_permission` | `prompts/txn/DEEVOFLOW_LEAD_SCREEN.md` |
| A menu entry | `nav.menu_module` / `nav.menu_item` rows tied to a permission or report | `sql/nav_menu_seed_v1.sql`, `prompts/nav/NAV_FRONTEND_PROMPT.md` |

Report procedures run on a connection whose `SESSION_CONTEXT` holds the caller's `tenant_id`
and `user_id` (`mtf.rpt.execution.connection`), with bound parameters and a statement timeout
(`DEEVO_REPORT_QUERY_TIMEOUT_SECONDS`). Procedures must filter by that tenant. The session's
business unit is **not** in `SESSION_CONTEXT` yet, so reports cannot filter by store.

---

## 10. Mailbox (Microsoft 365) connection — optional

`mtf.tenant` owns mailbox records (`email.mailbox`, `email.mailbox_credential`) and the OAuth
connect flow:

1. A system user calls `GET {API}/tenant/{tenant_id}/mailboxes/{mailbox_id}/authorize` and opens
   the returned `authorization_url`.
2. Microsoft redirects to the callback. It checks the signed `state`, exchanges the code,
   verifies the mailbox, stores the tokens, and redirects to `DEEVO_MAILBOX_OAUTH_SUCCESS_URL`.

Reading and sending mail is product code. It needs the `email` schema in the database.

---

## 11. Configuration

All settings are `DEEVO_*` environment variables read by `mtf.shared.config.get_settings()`
(cached; see `.env.example`). The host and every package read the same variables; set them once
in the deployment's app settings.

| Group | Settings |
|---|---|
| App | `DEEVO_APP_NAME`, `DEEVO_APP_VERSION`, `DEEVO_ENVIRONMENT` (`development` / `staging` / `production`), `DEEVO_DEBUG` |
| Database | `DEEVO_MSSQL_SERVER`, `DEEVO_MSSQL_PORT`, `DEEVO_MSSQL_DATABASE`, `DEEVO_MSSQL_USER`, `DEEVO_MSSQL_PASSWORD`, `DEEVO_MSSQL_ODBC_DRIVER`, `DEEVO_MSSQL_ENCRYPT`, `DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE`, `DEEVO_MSSQL_URL_MINIMAL` — or one `DEEVO_DATABASE_URL` |
| JWT | `DEEVO_JWT_SECRET_KEY`, `DEEVO_JWT_ALGORITHM`, `DEEVO_JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `DEEVO_JWT_REFRESH_TOKEN_EXPIRE_DAYS` |
| CORS | `DEEVO_ALLOWED_ORIGINS` (JSON list), `DEEVO_CORS_ALLOW_CREDENTIALS` |
| Proxy / client IP | `DEEVO_TRUSTED_PROXIES` (JSON list of IPs / CIDRs; set it behind a load balancer) |
| Login throttling | `DEEVO_LOGIN_MAX_FAILURES_PER_IP`, `DEEVO_LOGIN_MAX_FAILURES_PER_ACCOUNT_IP`, `DEEVO_LOGIN_FAILURE_WINDOW_SECONDS`, `DEEVO_LOGIN_ACCOUNT_LOCKOUT_THRESHOLD`, `DEEVO_LOGIN_ACCOUNT_LOCKOUT_MINUTES` |
| Reports | `DEEVO_REPORT_QUERY_TIMEOUT_SECONDS` |
| Microsoft mailbox | `DEEVO_MICROSOFT_CLIENT_ID`, `DEEVO_MICROSOFT_CLIENT_SECRET`, `DEEVO_MICROSOFT_AUTHORITY`, `DEEVO_MICROSOFT_REDIRECT_URI`, `DEEVO_MAILBOX_OAUTH_SUCCESS_URL` |
| Tests | `DEEVO_SKIP_DB_TESTS` |

**With `DEEVO_ENVIRONMENT=production` the app refuses to start** if:
- the JWT secret is weak or a placeholder;
- the database connection is not encrypted and certificate-verified;
- an origin is not `https://`;
- the mailbox success URL is not `https://`.

The checklist is in [security.md](security.md) §1. Package settings use their own prefix
(`DEEVO_<PACKAGE>_*`) in the package's own `Settings` class.

**CORS credentials:** keep `DEEVO_CORS_ALLOW_CREDENTIALS=true` if the frontend uses the
`/auth/browser/*` endpoints, which set the refresh cookie. Use `false` only if every frontend
sends Bearer tokens alone.

---

## 12. Testing the host

- **Unit tests:** override dependencies instead of creating tokens.

  ```python
  from mtf.shared.deps import CurrentUser, get_current_user

  app.dependency_overrides[get_current_user] = lambda: CurrentUser(
      user_id="01H...", user_type="app_user", user_scope="tenant",
      tenant_id="01H...", business_unit_id="01H...")
  ```

  With `business_unit_id=None`, only roles held at the root count. `require_scope`,
  `require_permission` and `require_screen_permission` sit on top of `get_current_user`;
  override the specific checker if a test must avoid a database lookup.
- **Integration tests:**
  - Log in through `POST {API}/auth/login` with real users; never build tokens by hand (a token
    without a live session is rejected).
  - **Staff logins must send `"business_unit_code": "MAIN"`** (every new staff member may use
    `MAIN`).
  - Create tenants through `POST {API}/tenant/` so they get their root and `MAIN`.
- **Clean-up:** soft-delete test tenants and users in the database (with `mark_deleted`) in a
  `finally` block. An API delete in a teardown can silently fail once auth overrides are reset.
- **Throttle reset:** the login throttle is per process, and every TestClient request comes from
  `testclient`. Add this to `tests/conftest.py`:

  ```python
  @pytest.fixture(autouse=True)
  def reset_login_throttle():
      from mtf.auth.services.login_throttle import login_throttle
      login_throttle.clear()
      yield
      login_throttle.clear()
  ```
- `DEEVO_SKIP_DB_TESTS=1`, or `pytest -m "not integration"`, skips the tests that need SQL
  Server.

---

## 13. Rules (summary)

| Do | Don't |
|---|---|
| Depend on `mtf.shared.deps` for every protected route | Decode or create JWTs yourself |
| Take tenant, store and account from `CurrentUser` / the dependencies | Accept `tenant_id` or `business_unit_id` from the body or query for scoping |
| Give tenant tables `tenant_id` + `business_unit_id` with the composite FK, and filter by both | Store tenant data without a business unit, or write owned rows at the root |
| Write audit rows with `audit_*` in the same transaction | Write to `audit.*` or other framework tables directly |
| Raise errors with `mtf.shared.exceptions` | Return ad-hoc error shapes |
| Use your own `DeclarativeBase` and schema | Add models to `mtf`'s `Base` or to framework schemas |
| Mount framework routers as they are | Wrap, proxy or copy framework routes and response models |
| Seed reports, screens, menus and permissions with SQL scripts in your repo | Put product logic in `mtf`, or patch / monkeypatch it |
| Keep middleware and CORS in the host | Add middleware or startup hooks in a package |
| Ask for framework changes in the framework repo | Edit an installed `mtf` |

---

## 14. Upgrading the framework

1. Read the framework's release notes, this guide and [security.md](security.md) for behaviour
   changes.
2. Bump the pin (`uv lock --upgrade-package deevo-mt-framework-backend`).
3. Run the host's tests, including the OpenAPI snapshot and the integration suite against the
   target database.
4. Deploy to staging, smoke-test login, refresh, a store switch, a report run and a screen, then
   promote.

### Upgrade notes — business units (Nov 2026)

A host that used `mtf` before business units must check:

| Change | Action in the host |
|---|---|
| Needs a database with `tenant.business_unit` (e.g. `deevo_app_dev3`) | Point `DEEVO_MSSQL_DATABASE` at it; product schemas must exist there too |
| Staff login requires `business_unit_code` | Login screens and tests send it |
| New routes `/auth/session/business-unit` (+ browser variant); new response and `/me` fields | Nothing if routers are mounted as they are; otherwise pass them through |
| `PermissionResolver` actors need `business_unit_id` | Pass `CurrentUser` |
| `utc_naive_now` removed | Use `mtf.shared.clock.utc_now` |
| `deleted_by` is required on the tenant / membership / account / address soft-delete services | Always pass the acting user id |
| `TenantUser.invite_token` removed | Remove the use |
| Framework tables reject rows without `business_unit_id` | Don't insert into them directly (§8) |
| Custom roles are held at a store, not the root | Assign through the API; pass `business_unit_id` for a specific store |
