# Security review — deevo_mt_framework_backend

Branch: `feature/claude` · Review date: 2026-11-21 · Status: **all 10 findings fixed, merged to `main`**

This document records what the security review found, what was changed, what is still open,
and what **must be configured before deploying to production** (several settings now stop the
app from starting if they are unsafe).

| Reader | Read |
|---|---|
| Deploying MTF or `deevo_api` | §1 Production checklist |
| Working on **`deevo_api`** or a new package (`deevo_integration`, `deevo_crm`, `deevo_workflow`, …) | §1, then **§2 Changes needed in deevo_api and the new packages** |
| Working on **deevoflow_react** | [frontend_security.md](frontend_security.md) |
| Reviewing this branch | §3 – §5 |

---

## 1. Production checklist

The app **refuses to start** when `DEEVO_ENVIRONMENT=production` and any of the items marked
**Required** is wrong. In `development` / `staging` the same problems only log a warning.

| # | Setting | Required value in production | Why | Fix |
|---|---|---|---|---|
| 1 | `DEEVO_JWT_SECRET_KEY` | **Required.** Not a placeholder; ≥ 32 bytes for HS256 (48 for HS384, 64 for HS512) | Short/known secrets let anyone forge tokens | #7 |
| 2 | `DEEVO_JWT_ALGORITHM` | **Required.** `HS256`, `HS384` or `HS512` | Only HMAC is supported | #7 |
| 3 | `DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE` | **Required.** `false` | Otherwise the DB certificate is never checked | #9 |
| 4 | `DEEVO_MSSQL_ENCRYPT` | **Required.** `true` | Production always sends `Encrypt=yes;TrustServerCertificate=no` | #9 |
| 5 | `DEEVO_DATABASE_URL` (if used) | **Required.** Must contain `Encrypt=yes` (or `strict`) and must not contain `TrustServerCertificate=yes` | Same as above for a raw URL | #9 |
| 6 | SQL Server certificate | **Required.** Issued by a CA the app host trusts (Azure SQL already is) | The dev server uses a **self-signed** certificate and fails verified TLS | #9 |
| 7 | `DEEVO_ALLOWED_ORIGINS` | **Required.** Explicit JSON list of `https://host[:port]` origins — no `*`, `null`, `http://`, paths or trailing `/` | The built-in default is the localhost list, which production rejects | #10 |
| 8 | `DEEVO_MAILBOX_OAUTH_SUCCESS_URL` | **Required.** `https://…` page of the admin app | Browser lands here after Microsoft consent | #2 |
| 9 | `DEEVO_TRUSTED_PROXIES` | **Set if behind a proxy / load balancer** (JSON list of proxy IPs/CIDRs). Leave `[]` if uvicorn is exposed directly | Otherwise every user appears to share the proxy's IP, and login throttling would block everyone together | #8 |
| 10 | `DEEVO_CORS_ALLOW_CREDENTIALS` | Optional. Default `true`. **Keep `true` if any frontend uses `/auth/browser/*`** (refresh token in an `HttpOnly` cookie); `false` only if every frontend uses Bearer tokens alone | `/auth/browser/login`, `/refresh` and `/logout` set and read a cookie, which needs credentialed CORS | #10 |
| 11 | `DEEVO_LOGIN_*` limits | Optional. Defaults below | Tune login throttling | #8 |

Generate a JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

> Changing `DEEVO_JWT_SECRET_KEY` signs everyone out once (existing tokens stop verifying).

Login throttling defaults (in memory, **per worker process** — with N workers/instances an
attacker gets up to N× these numbers; counters reset on restart):

| Setting | Default | Effect |
|---|---|---|
| `DEEVO_LOGIN_MAX_FAILURES_PER_ACCOUNT_IP` | 5 | Wrong passwords for one account from one IP → that IP gets HTTP 429 for that account |
| `DEEVO_LOGIN_MAX_FAILURES_PER_IP` | 30 | Wrong passwords from one IP across any accounts → 429 |
| `DEEVO_LOGIN_FAILURE_WINDOW_SECONDS` | 900 | Sliding window for both counters |
| `DEEVO_LOGIN_ACCOUNT_LOCKOUT_THRESHOLD` | 50 | Account-wide lock (all IPs combined) |
| `DEEVO_LOGIN_ACCOUNT_LOCKOUT_MINUTES` | 15 | Length of the account-wide lock |

All of these are documented in `.env.example`.

## 2. Changes needed in deevo_api and the new packages

`mtf` is consumed by **`deevo_api`** (the single deployable app, see
[architecture.md](architecture.md)) and the packages it mounts (`deevo_integration`,
`deevo_crm`, `deevo_workflow`, …). `deevo_api` installs `mtf`, mounts its routers under
`/api/v1` (`auth`, `tenant`, `reports`, txn screens, `audit`) and builds its **own** FastAPI app
in its own `main.py`. That decides what it gets for free and what it must do itself.

> **Old backend (`deevoflow_backend`).** It stays frozen until the cutover
> ([architecture.md](architecture.md) §12). If it keeps running on the *old* `mtf`, it does
> **not** get these fixes — notably #1, the unauthenticated mailbox `/authorize`. Keep that
> window short. If the cutover slips beyond a few days, upgrade its `mtf` and apply B1–B10
> there too (the same tasks, with `deevoflow_backend` in place of `deevo_api`).

### 2.1 Applies automatically (restart `deevo_api` after updating MTF)

Everything that lives in MTF services and dependencies:

| Fix | What users of `deevo_api` will notice |
|---|---|
| #1 Mailbox OAuth | `/api/v1/tenant/{tenant_id}/mailboxes/{mailbox_id}/authorize` needs a **system** Bearer token and returns JSON `{"authorization_url": ...}` instead of redirecting |
| #2 Mailbox errors / redirect | Generic error messages; redirect after consent comes from `DEEVO_MAILBOX_OAUTH_SUCCESS_URL` |
| #3 Audit readers | `/api/v1/audit/logs` → **403** for tenant members and non-admin portal users |
| #4 Session revocation | Logout, refresh, deactivation and membership removal end access immediately (**401**); removed staff and users of a suspended tenant can no longer refresh |
| #6 Token types | Access tokens without `typ="access"` / `sid` get **401**; refresh accepts only refresh tokens |
| #7, #9, #10 startup checks | Run inside `deevo_api` too, because it loads MTF `Settings` (MTF's DB engine is created from it). **`deevo_api` will refuse to start in production** until §1 is satisfied |
| #8 Login throttling | `/api/v1/auth/login` can return **429 `AUTH_RATE_LIMITED`** with `Retry-After` |

### 2.2 Must do

**Where:** `deevo_api` = the composition app; **packages** = `deevo_integration`, `deevo_crm`,
`deevo_workflow` and later modules.

| # | Where | Task | Why | Done when |
|---|---|---|---|---|
| B1 | `deevo_api` | **Pin the new MTF** and re-sync (`uv lock` / `uv sync`) | MTF now depends on **PyJWT** (not `python-jose`), FastAPI ≥ 0.165 / Starlette ≥ 1.3.1, python-multipart ≥ 0.0.31, `httpx` (runtime) | App starts; `pip-audit` clean |
| B2 | packages, `deevo_api` | Never import **`jose`**; use PyJWT (`import jwt`; `jwt.ExpiredSignatureError`, `jwt.InvalidTokenError`; unverified claims: `jwt.decode(t, options={"verify_signature": False})`). Do not add `python-jose` as a dependency (unmaintained, unfixed `ecdsa` advisory) | `python-jose` is no longer installed through MTF | `grep -rn "jose" --include=*.py` finds nothing |
| B3 | packages, `deevo_api` | Version ranges must allow FastAPI ≥ 0.165 / Starlette ≥ 1.3.1 | Older pins would block the security upgrade | Resolver succeeds |
| B4 | `deevo_api` | **Use the hardened CORS setup in `main.py`** (snippet below) | Without `expose_headers=["Retry-After"]` the React app cannot read the login 429 wait time | Preflight from the React origin OK; `Access-Control-Expose-Headers: Retry-After` present |
| B5 | `deevo_api`, and any package whose tests log in | Add the **throttle-reset fixture** to `tests/conftest.py` (snippet below) | The login throttle is per process and every TestClient request comes from `testclient`; deliberate failed logins in one test will 429 later ones (including system login) | Integration suite has no unexpected 429s |
| B6 | packages, `deevo_api` | Never **create access tokens** directly (`create_access_token(...)` without `session_id=`, or hand-built JWTs) — always issue tokens through MTF login/refresh | Such tokens have no `sid` and are rejected with 401 | grep (below) finds no such calls |
| B7 | packages, `deevo_api` | Every protected route depends on MTF's **`get_current_user`** (or `require_*` helpers built on it) — no own copy, no direct **`decode_token`** | Otherwise those routes skip session revocation, membership checks and token-type checks (#4, #6) | All protected routes depend on `mtf.shared.deps.get_current_user` |
| B8 | packages, `deevo_api` | Tests expect tenant **members** to get 403 on audit logs, and 401 when reusing an access token after refresh/logout | Behaviour change from #3, #4 | Tests green |
| B9 | `deevo_integration` (or wherever mailbox setup lives), admin app | Follow the new **mailbox OAuth** contract (fetch `authorization_url` with a system token, then open it); register the right `DEEVO_MICROSOFT_REDIRECT_URI` for the `deevo_api` URL in Entra ID | #1 | Mailbox authorization works end to end |
| B10 | `deevo_api` on Azure | Set the production values from §1 in the app settings (it reads the same `DEEVO_*` variables) | Startup checks | `deevo_api` starts with `DEEVO_ENVIRONMENT=production` |

Find B2, B6, B7, B8 quickly (run from each repo):

```bash
grep -rnE "from jose|import jose|create_access_token|decode_token|def get_current_user|CORSMiddleware|audit/logs" --include=*.py . | grep -v "/.venv/"
```

**B4 — CORS in `deevo_api` `main.py`** (exact `https://` origins in production, never `*`):

```python
from mtf.shared.config import get_settings

settings = get_settings()  # origins validated at startup (see MTF #10)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)
```

**B5 — `tests/conftest.py`:**

```python
@pytest.fixture(autouse=True)
def reset_login_throttle() -> None:
    """Process-wide login throttle; every TestClient request comes from ``testclient``."""
    from mtf.auth.services.login_throttle import login_throttle

    login_throttle.clear()
    yield
    login_throttle.clear()
```

**Smoke test after the changes** (`deevo_api` on port 8010):

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8010/api/v1/auth/me
curl -s -i -X OPTIONS http://localhost:8010/api/v1/auth/login -H "Origin: http://localhost:5173" -H "Access-Control-Request-Method: POST" | grep -i "access-control"
```

The first should print `401`. The second should show `access-control-allow-origin` for the
React origin (if it is in `DEEVO_ALLOWED_ORIGINS`) and `access-control-expose-headers: Retry-After`
on actual responses.

### 2.3 Frontend

The React tasks (handling the new 401/403/429 responses, plus the frontend's own security
findings) are in **[frontend_security.md](frontend_security.md)**. Do §2.2 first: the frontend
can only read `Retry-After` once B4 is deployed.

---

## 3. What was done

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | 🔴 Critical | Mailbox OAuth: `/authorize` had no auth and the callback trusted an unsigned base64 `state`, so anyone could attach their own Microsoft mailbox tokens to another tenant's mailbox | `/authorize` requires system scope and returns JSON. `state` is a signed, 10-minute token bound to tenant, mailbox and the admin who started the flow, signed with a key derived for that purpose only (so it can never work as a Bearer token). The callback rejects a Microsoft account that cannot open that mailbox's inbox (Graph check) and returns a generic error, with Microsoft's details logged only |
| 2 | 🟠 | Mailbox OAuth details: Microsoft error text returned to callers; redirect URL hard-coded to localhost | Token-refresh failures return a generic `400 MAILBOX_TOKEN_BAD_REQUEST` (details kept in `last_error` and logs). Redirect is the `DEEVO_MAILBOX_OAUTH_SUCCESS_URL` setting (https required in production). **Token encryption deferred** — see §4 |
| 3 | 🟠 | Any tenant staff member could read the whole tenant's audit trail (emails from `login_failed`, role changes, before/after values) | Readers limited to system users, tenant admins (`auth.tenant_user.role='admin'`) and account admins. Scoping by JWT tenant/account unchanged |
| 4 | 🟠 | Logout, refresh, user deactivation and membership removal did not revoke access tokens (valid until expiry) | Access tokens carry `sid`. Every request checks — in one primary-key lookup — that the session is active and not revoked, the token is the session's current one, and the user is active; tenant/portal users must also have an active membership. **`/refresh`** now also re-checks that the tenant is active (tenant and portal users) and that tenant staff still have an active membership; if not, the session is ended (`revoke_reason` `tenant_inactive` / `membership_inactive`) and 401 is returned |
| 5 | 🟠 | 43 known CVEs across 10 packages; `python-jose` unmaintained (`ecdsa` advisory unfixed); `httpx` used at runtime but only a dev dependency | Upgraded Starlette, FastAPI, python-multipart, anyio, dnspython, idna, pydantic-settings, certifi. Replaced `python-jose` with PyJWT (removes `ecdsa`, `pyasn1`, `rsa`, `cryptography`). `httpx` is now a runtime dependency. `pip-audit`: **0 known vulnerabilities** |
| 6 | 🟡 | Access and refresh tokens shared a key with no type claim; unknown `user_scope` / `user_type` silently defaulted to `tenant` / `app_user` | Tokens carry `typ` (`access` / `refresh`); each endpoint accepts only its own type. Unknown scope/type is rejected with 401 before any DB query. Legacy refresh tokens without `typ` are still accepted (they are also bound to the session's stored hash) |
| 7 | 🟡 | Production only rejected 4 exact placeholder JWT secrets; any algorithm string accepted | Placeholders (case/space-insensitive) and secrets shorter than the RFC 7518 minimum are fatal in production and a warning elsewhere. Algorithm restricted to HS256/384/512. Errors never echo the secret |
| 8 | 🟡 | No login rate limiting; 5 wrong passwords locked an account for everyone (anyone knowing an email could lock the user out) | In-memory throttle per (account, IP) and per IP, checked before bcrypt and before any audit write. Account-wide lock raised to 50 failures as a backstop. Client IP from the socket by default; `X-Forwarded-For` only from `DEEVO_TRUSTED_PROXIES` |
| 9 | 🟡 | DB certificate trusted unconditionally; with ODBC Driver 17 and `URL_MINIMAL=true`, traffic was **not encrypted at all** | Production always uses `Encrypt=yes;TrustServerCertificate=no` and refuses trust/no-encrypt settings (including inside `DEEVO_DATABASE_URL`). Dev URL unchanged, with a warning |
| 10 | 🟡 | CORS: `allow_credentials=True` with `*` methods/headers; origins not validated | Origins validated at startup (exact `scheme://host[:port]`; production https-only, no `*`/`null`). Explicit method list. `Retry-After` exposed. Credentials configurable |

### Main files changed

| Area | Files |
|---|---|
| Tokens, OAuth state | `mtf/shared/security.py` |
| Request authentication | `mtf/shared/deps.py` |
| Login, refresh, throttling | `mtf/auth/services/session_service.py`, `mtf/auth/services/login_throttle.py` (new) |
| Client IP | `mtf/shared/client_ip.py` (new) |
| Settings and startup checks | `mtf/shared/config.py`, `.env.example` |
| Mailbox OAuth | `mtf/tenant/api/tenant.py`, `mtf/tenant/services/mailbox_service.py`, `mtf/tenant/schemas/mailbox.py` |
| Audit read access | `mtf/audit/api/deps.py` |
| CORS | `main.py` |
| Dependencies | `pyproject.toml`, `uv.lock` |

### Tests

- **Unit suite: 991 passed** (162 skipped — they need a live SQL Server).
- New test files: `tests/tenant/test_mailbox_oauth.py`, `tests/shared/test_current_user_session.py`,
  `tests/shared/test_client_ip.py`, `tests/shared/test_cors.py`, `tests/auth/test_login_throttle.py`,
  `tests/auth/test_login_rate_limit.py`, `tests/auth/test_refresh_token_type.py`, `tests/auth/test_refresh_membership.py`,
  `tests/auth/test_session_revocation_integration.py`, `tests/auth/test_login_rate_limit_integration.py`;
  extended: `tests/shared/test_security.py`, `tests/shared/test_settings_deevobe_aliases.py`,
  `tests/audit/test_audit_api.py`, `tests/audit/test_audit_integration.py`.
- Each fix was checked by running its new tests against the **old** code (they fail) and the
  fixed code (they pass). For #1 the original attack was replayed: the old code stored the
  attacker's tokens; the fixed code returns 400 and stores nothing.
- Live-database tests for #3, #4 (including refresh after removal / tenant suspension), #6 and #8: **16/16 passed**.
- Full live-database suite with **every change applied: 1123 passed**; the only failures are
  the **same 23 that already failed before any change** (see §4) — no regressions.
- `tests/conftest.py` now resets the login throttle before each test (all TestClient requests
  share one address, so failures in one test could otherwise rate-limit another).

---

## 4. What is pending

| Item | Why it is open | Suggested next step |
|---|---|---|
| **Encrypt mailbox OAuth tokens at rest** (`email.mailbox_credential.access_token` / `refresh_token`, `Mail.ReadWrite` scope) | Deferred on purpose: another service reads these columns directly from the database, and would break until it can decrypt them | Agree an envelope format (e.g. Fernet/AES-GCM with a key from Key Vault, `enc:v1:` prefix, key rotation) with the reading service, then encrypt on write and re-encrypt legacy rows on next refresh |
| **Shared mailboxes cannot be authorized** | Since #1 the callback requires the consenting account to open the mailbox's inbox. The app only requests `Mail.ReadWrite`, not `Mail.ReadWrite.Shared` | If shared mailboxes are needed, add the `.Shared` scope (and admin consent in Entra ID) |
| **Admin UI uses the new `/authorize` contract** | Lives in another repository | Fetch `authorization_url` with the system token, then open it |
| **`deevo_api` and package follow-ups** | Live in other repositories | §2.2 tasks B1–B10; also for `deevoflow_backend` if the cutover slips |
| **deevoflow_react follow-ups** | Lives in another repository | [frontend_security.md](frontend_security.md) |
| **Login throttle is per process** | In-memory by agreement | If you run several workers/instances, move counters to a shared store (DB table or Redis) |
| **Test database is out of date** | 23 live tests fail without any of these changes: 15 because the seed is missing permissions such as `screen.lead.view`, 8 schema/trigger checks that pass when run alone but fail in the long full run | Re-seed / migrate the test DB so the integration suite is green and real regressions are visible |
| **Local `.env`** | `DEEVO_JWT_SECRET_KEY` is a placeholder value; DB uses Driver 17 + trust-all certificate | Fine for local development (warnings only); make sure no deployed environment copies it |
| Pre-existing lint (`ruff`) findings | Not part of this work (e.g. late import in `main.py`) | Clean up separately |

---

## 5. Not changed (reviewed and found sound)

- Report and lookup execution: stored procedures called with bound parameters, strict proc
  and parameter-name patterns, statement timeouts; no SQL built from strings anywhere.
- Tenant isolation: `tenant_id` always comes from the JWT, never from the request body; report
  connections set `SESSION_CONTEXT`.
- Report RBAC: users see only reports granted to them (`role_report.can_view`); unauthorized
  reports return 404, same as unknown ones.
- Refresh tokens rotate and are stored only as SHA-256 hashes; passwords use bcrypt.
- Audit rows strip secrets (`sanitize_audit_values`).
