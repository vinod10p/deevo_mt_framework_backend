# Prompt — Audit CRM Lead writes on DeevoFlow

Paste this whole file into a **Cursor chat whose workspace is `deevoflow_backend`**. Do not implement this from `deevo_mt_framework_backend` except the one Decimal sanitizer fix called out below.

The shared trail is `audit.audit_log` (v2, already on `deevo_app_dev2`). MTF helpers already exist: `audit_insert`, `audit_update`, `audit_soft_delete`, `row_snapshot`, `get_audit_source`. This product work is **Lead only**: write a trail row in the same transaction as each Lead mutation.

This repo’s rules win on URL prefix, commits-in-the-service, and error codes (`docs/CONVENTIONS.md`).

---

## Product decisions — these win over anything else in this file

1. **Same table, same helpers.** Use `mtf.audit.service`. Do not create `crm.audit_log`. Do not copy helper code into `app/`.
2. **Audit in `LeadService`, not in the two HTTP modules.** `/api/v1/crm/leads` and `/api/v1/crm/lead-screen` both write through `LeadService`. One wiring covers both UIs. `LeadScreenService` only forwards `actor` / `source`.
3. **Data-change trail only.** Audit `insert` / `update` / `delete` (soft delete). Do not audit GET/list. Do not store HTTP method, path, or bodies. `request_id` is the middleware ULID, never inbound `X-Request-ID`.
4. **`schema_name='crm'`, `table_name='lead'`, `tenant_id` from the JWT / `Lead.tenant_id`.** Always pass `tenant_id=` into the helper (tenant staff JWT has it; be explicit anyway).
5. **No other CRM entities in this work.** Account, contact, opportunity, task, note, lookup stay unaudited until a later prompt.
6. **No DDL.** Do not change `crm.lead`. Do not DELETE `audit.audit_log` rows in tests.

---

## Prerequisite

| Item | Expected |
|------|----------|
| Helpers | `from mtf.audit.service import AuditSource, audit_insert, audit_update, audit_soft_delete, row_snapshot` |
| Source dep | `from mtf.audit.api.deps import get_audit_source` |
| Middleware | `AuditRequestIdMiddleware` already in DeevoFlow `main.py` (mount-audit prompt). If missing, still write rows, but `request_id` will be null — say so, do not skip Lead wiring. |
| Read API | `GET /api/v1/audit/logs` if the mount prompt was done; otherwise tests can `select(AuditLog)` via `SessionLocal`. |

If `from mtf.audit.service import audit_insert` fails, stop. Do not vendor a copy.

---

## Master instructions

Inspect first:

- `app/crm/services/lead.py` — `create`, `update`, `update_fields`, `soft_delete`, `soft_delete_versioned`, `_versioned_update`
- `app/crm/api/lead.py` and `app/crm/api/lead_screen.py`
- `app/crm/services/lead_screen.py` (wraps `LeadService`)
- Sibling reference: `../deevo_mt_framework_backend/mtf/tenant/services/tenant_service.py`

Do **not**:

- Audit reads, report `/run`, txn GET, chat, WhatsApp, SMS, other CRM entities.
- Call `commit()` inside the audit helper (it never commits). Keep DeevoFlow’s **commit in the service**, but **add the audit row before `commit()`**.
- Use FastAPI `BaseHTTPMiddleware`.
- Log passwords/tokens (Lead has none; still go through the sanitizer so `row_version` is dropped).
- Commit git unless the user asks.

Implement **only** the step named in the user message. After each step: files changed, APIs, tests, assumptions, pending.

---

## What is already true

| Item | Actual |
|------|--------|
| App | `http://localhost:8010`, prefix `/api/v1` |
| Old Lead API | `app/crm/api/lead.py` → `create` / `update` / `soft_delete` (ORM mutate + `commit`) |
| Screen API | `app/crm/api/lead_screen.py` → `LeadScreenService` → `create` / `update_fields` / `soft_delete_versioned` |
| Screen updates | `_versioned_update` runs a **conditional SQL `UPDATE`** then **commits inside that helper**. ORM instance is stale until refresh. Optimistic 409 if `rowcount != 1`. |
| Converted leads | `update` → 404; screen update/delete → 403 `CRM_LEAD_FORBIDDEN`. No audit row on those failures. |
| Services today | Keyword-only `created_by` / `updated_by` / `deleted_by`. No `actor` / `source`. |

---

## Target contract

Every successful Lead insert/update/soft-delete writes **one** `audit.audit_log` row in the **same** transaction:

| Method | `action` | `old_values` | `new_values` |
|--------|----------|--------------|--------------|
| `create` | `insert` | null | full snapshot (sanitized) |
| `update`, `update_fields` | `update` | changed keys only | same keys |
| `soft_delete`, `soft_delete_versioned` | `delete` | before snapshot | after snapshot (`is_deleted` false → true) |

Row identity:

- `schema_name="crm"`, `table_name="lead"`, `record_id=lead.id`
- `tenant_id=lead.tenant_id`
- `user_id` / `user_type` from `actor` (`tenant`)
- `request_id` from `source` (26-char ULID once middleware is mounted)
- JSON objects only. `row_version` omitted. No secrets.

`audit_update` writes **nothing** when no field actually changed (helper already returns `None`). Keep that.

Failed validation / 404 / 403 / 409: **no** audit row (rollback or never add).

---

## Step 1 — `LeadService` writers

Add keyword-only `actor: CurrentUser | None = None` and `source: AuditSource | None = None` next to the existing `created_by` / `updated_by` / `deleted_by` args on:

- `create`
- `update`
- `update_fields`
- `soft_delete`
- `soft_delete_versioned`

Pattern for ORM paths (`create`, `update`, `soft_delete`) — same as `TenantService`:

```python
self._db.add(row)
audit_insert(
    self._db,
    entity=row,
    schema_name="crm",
    table_name="lead",
    actor=actor,
    source=source,
    tenant_id=tenant_id,
)
self._db.commit()
```

For `update` / `soft_delete`: `before = row_snapshot(row)` **before** mutating flags/fields, then `audit_update` / `audit_soft_delete`. Soft delete is always `action='delete'`, never `update`.

### `_versioned_update` (easy to get wrong)

Today it `UPDATE … WHERE row_version = ?` then `commit()`. Audit must see **after** state and must be in the **same** transaction.

Refactor so commit happens **after** audit:

1. `before = row_snapshot(row)` in the caller (`update_fields` / `soft_delete_versioned`), before the SQL.
2. Run the conditional `UPDATE` (keep the 409 `rowcount != 1` + rollback behavior).
3. **Do not commit yet.** `refresh(row)` in the same session so the ORM matches the database.
4. `audit_update` or `audit_soft_delete` with that `before` and the refreshed entity.
5. Then `commit()`.

Do not `setattr` the SQL values onto the instance and also emit the bulk `UPDATE` in a way that flushes a second UPDATE. Refresh-after-SQL is the safe path.

Pass `actor` / `source` into `_versioned_update` or keep audit in the two callers after a non-committing `_versioned_update`. Either is fine; do not leave commit inside `_versioned_update` with no audit.

---

## Step 2 — API + `LeadScreenService` pass-through

Thin routes. Add `source: AuditSource = Depends(get_audit_source)` and pass `actor=current_user`, `source=source` into the service.

- `app/crm/api/lead.py` — POST / PATCH / DELETE only. GET/list unchanged.
- `app/crm/api/lead_screen.py` — POST / PATCH / DELETE. GET unchanged.
- `LeadScreenService.create` / `update` / `delete` — accept `actor` / `source` and forward into `LeadService`. Do not write audit in `LeadScreenService`.

---

## Step 3 — Decimal sanitizer (only if needed)

`crm.lead.revenue` is `Numeric` / `Decimal`. `json.dumps` cannot encode `Decimal`.

If create/update with `revenue` raises `TypeError`, fix **once** in the sibling repo:

`deevo_mt_framework_backend/mtf/audit/service.py` → `sanitize_audit_values`: convert `decimal.Decimal` to `str` (preserve precision; do not use `float`). Add a unit test in MTF `tests/audit/test_append_audit_log.py`.

Do not special-case revenue in DeevoFlow. Do not skip auditing rows that have `revenue`.

---

## Step 4 — tests

### Unit (no database)

`tests/crm/test_lead_audit.py` — mock `Session` like MTF `tests/tenant/test_mutation_audit.py`:

- `create` adds an `AuditLog` with `action='insert'`, `schema_name='crm'`, `table_name='lead'`, `tenant_id` set, `request_id` from `AuditSource`, `old_values is None`, `first_name` in `new_values`, `row_version` absent.
- `update` (name/status change) writes `action='update'` with only changed keys.
- `soft_delete` writes `action='delete'` with `is_deleted` false → true.
- `commit` called once on the success path; helper never commits.
- Converted-lead update/delete raises and does **not** add `AuditLog`.

Patch `hash_password` only if a test hashes; Lead create does not.

### Live SQL (optional, `pytest.mark.integration`, skip on `DEEVO_SKIP_DB_TESTS`)

Extend or add next to `tests/crm/test_account_contact_lead_integration.py`:

- Tenant JWT: POST `/api/v1/crm/leads`, PATCH, DELETE.
- Then `GET /api/v1/audit/logs?schema_name=crm&table_name=lead&record_id=<id>` (if audit router mounted) **or** `select(AuditLog)` via `SessionLocal`.
- Expect insert, update, delete rows; `tenant_id` matches; `request_id` length 26 if middleware is on; inbound `X-Request-ID: client-trace` must not be stored.
- Soft-delete the lead in `finally`. **Never** `DELETE FROM audit.audit_log`.

Keep existing Lead/screen tests green. Do not weaken converted-lead 403/404 tests.

---

## Step 5 — docs (light)

In `docs/CONVENTIONS.md` or `docs/PROJECT_CONTEXT.md`, one short note: CRM Lead mutations write `audit.audit_log` via MTF helpers (`crm` / `lead`). Other CRM entities not yet. Point at sibling `docs/CONVENTIONS.md` Audit Logging for column rules. Do not paste the full MTF audit spec.

---

## Done when

- [ ] `LeadService` writes insert/update/delete audit rows before `commit()` on all five write methods
- [ ] Both Lead APIs pass `actor` + `source`
- [ ] `_versioned_update` no longer commits without an audit row
- [ ] GET/list unaudited
- [ ] Converted-lead failures write no row
- [ ] Unit tests pass; integration if DB is available
- [ ] No other CRM services changed
- [ ] `uv run ruff check` on touched files is clean

## Out of scope (later prompts)

- Account, contact, opportunity, task, note, lookup
- Lead conversion endpoint (when it exists: still `update` or a dedicated action — decide then)
- Workflow / chat
- HTTP access logging
- React audit UI
