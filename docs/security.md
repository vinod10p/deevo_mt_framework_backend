# Security review — deevo_mt_framework_backend

Branch: `feature/claude` · Review date: 2026-11-21 · Status: **all 10 findings fixed, not yet committed**

This document records what the security review found, what was changed, what is still open,
and what **must be configured before deploying to production** (several settings now stop the
app from starting if they are unsafe).

| Reader | Read |
|---|---|
| Deploying MTF or DeevoFlow | §1 Production checklist |
| Working on **deevoflow_backend** | §1, then **§2 Changes needed in deevoflow_backend** |
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
| 10 | `DEEVO_CORS_ALLOW_CREDENTIALS` | Optional. Default `true`; set `false` once no frontend uses `withCredentials` / `credentials: "include"` | Auth is Bearer-only; the backend sets no cookies | #10 |
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

## 2. Changes needed in deevoflow_backend

DeevoFlow installs `mtf` as an editable package, mounts its routers under `/api/v1`
(`auth`, `tenant`, `reports`, txn screens, `audit`) and builds its **own** FastAPI app in its
own `main.py`. That decides what it gets for free and what it must change itself.

### 2.1 Applies automatically (restart DeevoFlow after updating MTF)

Everything that lives in MTF services and dependencies:

| Fix | What DeevoFlow users will notice |
|---|---|
| #1 Mailbox OAuth | `/api/v1/tenant/{tenant_id}/mailboxes/{mailbox_id}/authorize` needs a **system** Bearer token and returns JSON `{"authorization_url": ...}` instead of redirecting |
| #2 Mailbox errors / redirect | Generic error messages; redirect after consent comes from `DEEVO_MAILBOX_OAUTH_SUCCESS_URL` |
| #3 Audit readers | `/api/v1/audit/logs` → **403** for tenant members and non-admin portal users |
| #4 Session revocation | Logout, refresh, deactivation and membership removal end access immediately (**401**); removed staff and users of a suspended tenant can no longer refresh |
| #6 Token types | Access tokens without `typ="access"` / `sid` get **401**; refresh accepts only refresh tokens |
| #7, #9, #10 startup checks | Run inside DeevoFlow too, because it loads MTF `Settings` (MTF's DB engine is created from it). **DeevoFlow will refuse to start in production** until §1 is satisfied |
| #8 Login throttling | `/api/v1/auth/login` can return **429 `AUTH_RATE_LIMITED`** with `Retry-After` |

### 2.2 Must do in deevoflow_backend

| # | Task | Why | Done when |
|---|---|---|---|
| B1 | **Re-sync dependencies** after pulling the new MTF (`uv sync` / `pip install -e`) | MTF now depends on **PyJWT** (not `python-jose`), FastAPI ≥ 0.165 / Starlette ≥ 1.3.1, python-multipart ≥ 0.0.31, `httpx` (runtime) | App starts; `pip-audit` clean |
| B2 | If DeevoFlow code imports **`jose`** anywhere, switch it to PyJWT (`import jwt`; `jwt.ExpiredSignatureError`, `jwt.InvalidTokenError`; unverified claims: `jwt.decode(t, options={"verify_signature": False})`) — or add `python-jose` to DeevoFlow's own deps (not recommended: unmaintained, unfixed `ecdsa` advisory) | `python-jose` is no longer installed through MTF | `grep -rn "jose" --include=*.py` finds nothing |
| B3 | Check DeevoFlow's own version pins don't conflict with FastAPI ≥ 0.165 / Starlette ≥ 1.3.1 | Older pins would block the security upgrade | Resolver succeeds |
| B4 | **Copy the CORS hardening into DeevoFlow's `main.py`** (see snippet below) | MTF's `main.py` changed, DeevoFlow's did not. Without `expose_headers=["Retry-After"]` the React app cannot read the login 429 wait time | Preflight from the React origin OK; `Access-Control-Expose-Headers: Retry-After` present |
| B5 | Add the **throttle-reset fixture** to DeevoFlow's `tests/conftest.py` (snippet below) | The login throttle is per process and every TestClient request comes from `testclient`; deliberate failed logins in one test will 429 later ones (including system login) | Integration suite has no unexpected 429s |
| B6 | Remove any code that **creates access tokens itself** (`create_access_token(...)` without `session_id=`, or hand-built JWTs) — always issue tokens through MTF login/refresh | Such tokens have no `sid` and are now rejected with 401 | grep (below) finds no such calls |
| B7 | Any code that authenticates by calling **`decode_token`** directly, or a DeevoFlow copy of **`get_current_user`**, must use MTF's `get_current_user` (or at least `decode_access_token`) | Otherwise those routes skip session revocation, membership checks and token-type checks (#4, #6) | All protected routes depend on `mtf.shared.deps.get_current_user` |
| B8 | Update DeevoFlow tests that expect tenant **members** to read audit logs (expect 403 now) and any that reuse an access token after refresh/logout (expect 401) | Behaviour change from #3, #4 | Tests green |
| B9 | If DeevoFlow handles the **mailbox OAuth callback** itself or links to `/authorize`, follow the new contract (fetch `authorization_url` with a system token, then open it); register the right `DEEVO_MICROSOFT_REDIRECT_URI` | #1 | Mailbox authorization works end to end |
| B10 | Set the production values from §1 in DeevoFlow's environment (it reads the same `DEEVO_*` variables) | Startup checks | DeevoFlow starts with `DEEVO_ENVIRONMENT=production` |

Find B2, B6, B7, B8 quickly (run from deevoflow_backend):

```bash
grep -rnE "from jose|import jose|create_access_token|decode_token|def get_current_user|CORSMiddleware|audit/logs" --include=*.py . | grep -v "/.venv/"
```

**B4 — CORS in DeevoFlow `main.py`** (keep DeevoFlow's own origin source if it has one, but apply
the same rules: exact `https://` origins in production, never `*`):

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

**Smoke test after the changes** (DeevoFlow on port 8010):

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
| **deevoflow_backend follow-ups** | Lives in another repository | §2.2 tasks B1–B10 |
| **deevoflow_react follow-ups** | Lives in another repository | [frontend_security.md](frontend_security.md) |
| **Login throttle is per process** | In-memory by agreement | If you run several workers/instances, move counters to a shared store (DB table or Redis) |
| **Test database is out of date** | 23 live tests fail without any of these changes: 15 because the seed is missing permissions such as `screen.lead.view`, 8 schema/trigger checks that pass when run alone but fail in the long full run | Re-seed / migrate the test DB so the integration suite is green and real regressions are visible |
| **Local `.env`** | `DEEVO_JWT_SECRET_KEY` is a placeholder value; DB uses Driver 17 + trust-all certificate | Fine for local development (warnings only); make sure no deployed environment copies it |
| Pre-existing lint (`ruff`) findings | Not part of this work (e.g. late import in `main.py`) | Clean up separately |
| **Commit / review** | All changes are uncommitted on `feature/claude` | Review each fix, then commit |

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
