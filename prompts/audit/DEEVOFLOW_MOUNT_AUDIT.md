# Prompt — Mount MTF audit on DeevoFlow

Paste this whole file into a **Cursor chat whose workspace is `deevoflow_backend`**. Do not implement this from `deevo_mt_framework_backend`.

The data-change audit trail already exists in the sibling framework (`mtf.audit`). Auth, tenant, session, and saved-view **writes** already call `append_audit_log` inside MTF services that this app mounts. This product work is **wiring only**: expose the read API on port 8010 and assign a per-request ULID so those writes get `request_id`.

This repo’s rules win on URL prefix and docs (`docs/CONVENTIONS.md`, `docs/PROJECT_CONTEXT.md`).

---

## Product decisions — these win over anything else in this file

1. **Mount, do not reimplement.** Use `mtf.audit.api.router` and `mtf.audit.middleware.AuditRequestIdMiddleware`. Do not copy models, schemas, services, or SQL into `app/`.
2. **Prefix is `/api/v1/audit`.** DeevoFlow uses `/api/v1/...`. MTF standalone uses `/api/audit`. The live paths here are `GET /api/v1/audit/logs` and `GET /api/v1/audit/logs/{log_id}`.
3. **No product mutation audit in this work.** Do not call `append_audit_log` / `audit_insert` / `audit_update` / `audit_soft_delete` from CRM, Lead screen, workflow, chat, WhatsApp, SMS, or integrations. Lead remains unaudited until a later prompt.
4. **No HTTP access log.** Do not store request/response bodies, method, or path. `audit.audit_log` is a data-change + auth-event trail. `request_id` is a backend ULID, never inbound `X-Request-ID`.
5. **No DDL.** `audit.audit_log` v2 is already on `deevo_app_dev2`. Do not run `sql/audit_schema_v2.sql` from this repo.

---

## Prerequisite (already true locally)

| Item | Actual |
|------|--------|
| Framework dep | `deevo-mt-framework-backend` path `../deevo_mt_framework_backend` editable |
| Shared DB | `.env` → `DEEVO_MSSQL_DATABASE=deevo_app_dev2` |
| MTF writers | Login / login_failed / logout, tenant CUD, users, accounts, addresses, mailbox **metadata**, report saved views |
| MTF readers | `GET /logs`, `GET /logs/{log_id}` — JWT scoped: system = all; tenant = that tenant; portal = tenant+account. Wrong tenant → **404** `AUDIT_LOG_NOT_FOUND`, not 403 |
| POST logs | Not mounted / 405 — do not add a write route |
| Runtime role | Production `deevo_app` is `GRANT SELECT, INSERT` / `DENY UPDATE, DELETE`. Local `.env` may use `deevo` (`db_owner`); do not try to DELETE audit rows in tests |

If `from mtf.audit.api import router` fails, stop and say the sibling checkout does not have the audit package yet. Do not vendor a copy into DeevoFlow.

**Azure later:** MTF audit must be on the framework `main` (or whatever the deploy vendors) before this mount ships. Local editable path sees the sibling working tree; CI/Azure does not until that is committed and the lock/vendored copy is updated. Do not bump versions or edit deploy workflows in this work.

---

## Master instructions

Inspect `main.py`, `docs/PROJECT_CONTEXT.md`, `docs/CONVENTIONS.md`, and existing mount tests (`tests/test_rpt_routes.py`, `tests/test_txn_routes.py`) first.

Do **not**:

- Reimplement audit in `app/`.
- Change CRM / Lead / wf / chat / WhatsApp / SMS / integration services.
- Mount `mtf.tenant.api.tenant_account_portal` unless it is already mounted.
- Add FastAPI `BaseHTTPMiddleware` for request id. Use MTF’s plain ASGI `AuditRequestIdMiddleware` (this app already avoids BaseHTTPMiddleware because of CORS + nested task groups).
- Delete or “clean up” `audit.audit_log` rows.
- Commit unless the user asks.

Implement **only** the step named in the user message. After each step: files changed, APIs, tests, assumptions, pending.

---

## What is already true in DeevoFlow `main.py`

| Item | Actual |
|------|--------|
| App | `http://localhost:8010`, prefix **`/api/v1`** |
| MTF mounts today | `/api/v1/auth`, `/api/v1/tenant`, `/api/v1/reports`, `/api/v1` txn screens |
| Middleware today | `CatchUnhandledExceptionsMiddleware`, then `CORSMiddleware` |
| Audit mount | **missing** |
| Request-id middleware | **missing** — without it, MTF writes still insert, but `request_id` is null |

---

## Target after this work

A system or tenant JWT against DeevoFlow can:

1. `POST /api/v1/auth/login` — already writes `login` / `login_failed` via MTF; after middleware, `request_id` is a 26-char ULID.
2. `GET /api/v1/audit/logs` — list (pagination `skip`/`limit`, max 200). Filters: `action`, `schema_name`, `table_name`, `record_id`, `request_id`, `user_id`, `tenant_id` (system only), `account_id`.
3. `GET /api/v1/audit/logs/{log_id}` — one row, or 404 `AUDIT_LOG_NOT_FOUND`.
4. `POST /api/v1/audit/logs` — **405**.

---

## Step 1 — mount + middleware

In `main.py`:

```python
from mtf.audit.api import router as mtf_audit_router
from mtf.audit.middleware import AuditRequestIdMiddleware

app.add_middleware(AuditRequestIdMiddleware)
app.include_router(mtf_audit_router, prefix="/api/v1/audit", tags=["audit"])
```

Place the include next to the other MTF routers. Adding `AuditRequestIdMiddleware` after CORS is fine (Starlette runs last-added first). Do not wrap it in BaseHTTPMiddleware. Do not change `CatchUnhandledExceptionsMiddleware`.

Update docs so they stay the source of truth:

- `docs/PROJECT_CONTEXT.md` — add `/api/v1/audit/*` to **Mounted from MTF**.
- `docs/CONVENTIONS.md` — add the audit include to the HTTP layout snippet and path table.

Do not rewrite the audit column/action spec here. Point at `../deevo_mt_framework_backend/docs/CONVENTIONS.md` (Audit Logging).

---

## Step 2 — tests

Add `tests/test_audit_routes.py` in the same style as `tests/test_rpt_routes.py` (OpenAPI, no database):

- `GET /api/v1/audit/logs` and `GET /api/v1/audit/logs/{log_id}` are in OpenAPI.
- Those paths have GET, not POST (or POST is 405 via TestClient).
- Unauthenticated `GET /api/v1/audit/logs` is 401 or 403.

Optional live check (only if `.env` can reach `deevo_app_dev2` and `DEEVO_SKIP_DB_TESTS` is not set), same skip pattern as other integration tests:

- Login as the seeded system user (`DEEVO_TEST_SYSTEM_EMAIL` / `DEEVO_TEST_SYSTEM_PASSWORD`, defaults used elsewhere: `vinod@deevolight.com` / `vinod123`).
- `GET /api/v1/audit/logs?action=login&limit=1` returns 200 and a list.
- If a row is present, `request_id` is either null (old rows from before the middleware) or a 26-char string, never the inbound `X-Request-ID` value. To prove middleware: send `X-Request-ID: client-trace` on login, then list that user’s latest `login` row and assert `request_id != "client-trace"` and `len(request_id) == 26`.

Do **not** `DELETE FROM audit.audit_log`. Soft-delete any tenant/user this test creates, the same way CRM/tenant integration tests already do.

---

## Step 3 — manual smoke (after restart)

Restart DeevoFlow so it loads the editable MTF package.

```bash
# from deevoflow_backend
curl -s -X POST http://localhost:8010/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"vinod@deevolight.com","password":"vinod123","created_from":"web"}'

curl -s http://localhost:8010/api/v1/audit/logs?limit=5 \
  -H "Authorization: Bearer <access_token>"
```

Confirm OpenAPI at `http://localhost:8010/docs` shows **audit**.

---

## Done when

- [ ] `main.py` mounts `mtf_audit_router` at `/api/v1/audit` and adds `AuditRequestIdMiddleware`
- [ ] Docs list the new mount
- [ ] OpenAPI/route tests pass
- [ ] No CRM/Lead/wf/chat writers were changed
- [ ] No SQL was run
- [ ] `uv run pytest tests/test_audit_routes.py tests/test_rpt_routes.py tests/test_txn_routes.py -q` is green

## Out of scope (later prompts)

- CRM / Lead / workflow / chat calling `append_audit_log`
- `export` / `import` / `access_denied` / `restore` product events
- HTTP request/response logging table
- React audit UI
