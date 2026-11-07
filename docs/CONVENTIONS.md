# deevo_mt_framework_backend — Conventions

This document records agreed conventions for persistence, HTTP APIs, authentication, testing, and database access for the **Deevo Multi-Tenant Framework** (`deevo_mt_framework_backend`).

Update this document when decisions change. This is the source of truth — code follows this document, not the other way around.

For **project identity, current build step, and scope**, see [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

---

## Quick reference

| Topic | Rule |
|-------|------|
| **IDs** | ULID as `VARCHAR(26)`; generate in services |
| **Table names** | Singular (`tenant`, `app_user`); login identity is **`auth.app_user`**, not `auth.user` |
| **SQL schemas (this repo)** | `auth`, `tenant`, `audit`, `rpt`, `txn` |
| **Soft delete** | `is_deleted` + `deleted_by`; never hard-delete mutable rows |
| **Queries** | Filter `is_deleted = False` unless intentionally listing deleted rows |
| **Layering** | `api/` → `services/` → models/DB; `audit` flat; `auth` / `tenant` / `rpt` split |
| **API routers** | One module per entity; `api/__init__.py` exports composed `router` |
| **HTTP prefix** | `/api/<domain>/...`; health at `GET /health` (no auth) |
| **Errors** | `{"code": "DOMAIN_ENTITY_REASON", "message": "..."}` — stable codes |
| **Concurrency** | `row_version` (ROWVERSION); PATCH sends base64; mismatch → `409` |
| **JSON fields** | `snake_case` only |
| **Config** | `DEEVO_*` via `mtf/shared/config.py`; see Configuration Reference below |

---

## Overview

`deevo_mt_framework_backend` is a standalone, reusable FastAPI backend that provides multi-tenant infrastructure: authentication, session management, tenant isolation, role-based access control, and auditing. It is product-agnostic — no CRM or domain-specific logic lives here.

Products (e.g. `deevo_crm_backend`) run as separate services and share the same SQL Server database, using separate SQL schemas.

---

## Platform

- **Database:** Microsoft **SQL Server 2022 or later** (2025 Standard Edition in production)
- **DB access (v1):** Synchronous SQLAlchemy `Session` + **pyodbc** only — no async engine in v1
- **Logical namespaces:** Tables grouped under SQL Server schemas: `audit`, `auth`, `tenant`, `rpt`, `txn` (framework-owned). Product schemas (`crm`, `email`, `scout`, `flow`) are owned by their respective product backends.
- **Python ORM:** SQLAlchemy 2.0 (`DeclarativeBase`, `Mapped`, `mapped_column`). Validation/serialisation: Pydantic v2 (`BaseModel`, `ConfigDict`).
- **Package manager:** `uv`. Use `uv add <package>` to add dependencies.

---

## Project Structure

```
deevo_mt_framework_backend/
├── mtf/                         ← main package (Multi-Tenant Framework)
│   ├── __init__.py
│   ├── shared/                  ← config, DB, security, deps, exceptions, schemas
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── security.py
│   │   ├── deps.py
│   │   ├── exceptions.py
│   │   └── schemas.py
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── api/
│   │   │   ├── __init__.py      # composes router from entity modules
│   │   │   ├── session.py       # login, logout, refresh
│   │   │   ├── app_user.py
│   │   │   ├── tenant_user.py
│   │   │   └── tenant_account_user.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── session.py
│   │   │   ├── tenant_user.py
│   │   │   └── tenant_account_user.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── session.py
│   │   │   ├── tenant_user.py
│   │   │   └── tenant_account_user.py
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── user.py
│   │       ├── session.py
│   │       ├── tenant_user.py
│   │       └── tenant_account_user.py
│   ├── tenant/
│   │   ├── __init__.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── tenant.py
│   │   │   ├── tenant_setting.py
│   │   │   ├── tenant_account.py
│   │   │   └── tenant_account_address.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── tenant.py
│   │   │   ├── tenant_setting.py
│   │   │   ├── tenant_account.py
│   │   │   └── tenant_account_address.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── tenant.py
│   │   │   ├── tenant_setting.py
│   │   │   ├── tenant_account.py
│   │   │   └── tenant_account_address.py
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── tenant.py
│   │       ├── tenant_setting.py
│   │       ├── tenant_account.py
│   │       └── tenant_account_address.py
│   ├── rpt/                     ← generic reporting (see REPORTING_FRAMEWORK_CONTEXT.md)
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── report.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── report_definition.py
│   │   │   ├── report_column.py
│   │   │   └── report_criteria.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   └── report.py
│   │   └── services/
│   │       ├── __init__.py
│   │       └── report_catalog.py
│   └── audit/                   ← flat layout (append-only, no update/delete)
│       ├── __init__.py
│       ├── api/
│       │   ├── __init__.py
│       │   └── audit_log.py
│       ├── models.py
│       ├── schemas.py
│       └── service.py
├── main.py                      ← FastAPI app entry point (standalone runnable)
├── docs/
│   ├── CONVENTIONS.md           ← this document (source of truth)
│   └── PROJECT_CONTEXT.md       ← project identity + current step (workflow)
├── prompts/                     ← Cursor/AI prompts used to generate code
├── tests/
│   ├── conftest.py
│   ├── auth/
│   │   └── __init__.py
│   ├── tenant/
│   │   └── __init__.py
│   └── audit/
│       └── __init__.py
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

---

## Domain Modules

| Module | SQL Schema | Purpose |
|--------|-----------|---------|
| `auth` | `auth` | Users, sessions, tenant-user and tenant-account-user membership |
| `tenant` | `tenant` | Tenants, accounts, addresses, settings |
| `audit` | `audit` | Immutable audit log for all data changes and auth events |
| `rpt` | `rpt` | Generic report catalog (definitions, columns, criteria, saved views) and execution |
| `shared` | — | Config, database, security, deps, exceptions, schemas |

---

## Frontend Applications

| App | Tech | User scope | Default port |
|-----|------|-----------|-------------|
| `deevo_admin` | Streamlit | `system` | `8501` |
| `deevo_crm` | React | `tenant` | `3000` |
| `deevo_portal` | React | `tenant_account` | `3001` |
| `deevo_account_st` | Streamlit | `tenant_account` | `8502` |

All frontends call `deevo_mt_framework_backend` (and/or their product backend) via HTTP.

---

## Database

### SQL Schemas

| SQL Schema | Owner | Tables |
|-----------|-------|--------|
| `auth` | `deevo_mt_framework_backend` | `app_user`, `session`, `tenant_user`, `tenant_account_user` |
| `tenant` | `deevo_mt_framework_backend` | `tenant`, `tenant_setting`, `tenant_account`, `tenant_account_address` |
| `audit` | `deevo_mt_framework_backend` | `audit_log` (DDL: [../sql/audit_schema_v2.sql](../sql/audit_schema_v2.sql); v1 dump still in [../sql/database_schema_v1.sql](../sql/database_schema_v1.sql)) |
| `rpt` | `deevo_mt_framework_backend` | `report_definition`, `report_column`, `report_criteria`, `report_saved_view`, `report_permission`, `report_action`, `report_action_param` (DDL: [rpt_schema_v5.sql](rpt_schema_v5.sql), additive V2 in [txn_schema_v2.sql](txn_schema_v2.sql)) |
| `txn` | `deevo_mt_framework_backend` | `screen`, `screen_section`, `screen_field`, `screen_field_config`, `lookup`, `lookup_column`, `screen_permission` (DDL: [txn_schema_v2.sql](txn_schema_v2.sql)). Metadata only — entity CRUD stays in product backends. |
| `crm` | `deevo_crm_backend` / `deevoflow_backend` | leads, contacts, accounts, deals, activities |

### Database Users

| User | Purpose | Permissions |
|------|---------|------------|
| `deevo_ddl` | Schema migrations only | `db_owner` |
| `deevo_app` | Application runtime | Read/write only — no DDL |

- Credentials via `.env` only — never commit passwords.
- Application always connects as `deevo_app` — never `deevo_ddl`.

---

## HTTP API Layout

- **URL prefix:** All REST routes live under `/api/` (e.g. `/api/auth/...`, `/api/tenant/...`). There is **no `/api/v1/` segment in v1** — if a breaking API revision is needed later, introduce `/api/v2/` and keep v1 until clients migrate.
- **Domain routers:** Each domain exposes an `APIRouter` from `mtf.<domain>.api`. The `api/` package `__init__.py` composes the router from one module per entity.
- **Health:** `GET /health` — unversioned, no auth, for load balancers and probes only.
- **CORS:** `CORSMiddleware` configured in `main.py` using `settings.allowed_origins`.
- **Mount pattern in `main.py`:**

```python
app.include_router(auth_router,   prefix="/api/auth")
app.include_router(tenant_router, prefix="/api/tenant")
app.include_router(audit_router,  prefix="/api/audit")
app.include_router(rpt_router,    prefix="/api")   # entity routers carry /reports
app.include_router(txn_router,    prefix="/api")   # entity routers carry /screens
```

---

## Layering

```
Client → mtf/<domain>/api/<entity>.py → mtf/<domain>/services/<entity>.py → (models, DB Session)
```

- **`api/`:** HTTP only. One `APIRouter` per entity file. No business logic — no direct `Session` access except via `Depends`. Delegates everything to the service layer.
- **`services/`:** All application logic — queries, mutations, transactions. Receives `Session` via constructor (`def __init__(self, db: Session)`). Raise errors via helpers in `mtf.shared.exceptions` (they raise `HTTPException` with stable `code` values). Do not import FastAPI in services except through those helpers.
- **`schemas/`:** Pydantic `BaseModel` classes for request/response shapes. Never imports from models directly — bridged via `from_attributes=True`.
- **`models/`:** SQLAlchemy `Base` subclasses. Persistence shape only — columns and relationships. No Pydantic inheritance.

### Layout Rules

- `audit` uses **flat layout**: `models.py`, `schemas.py`, `service.py` at domain root. HTTP under `api/`.
- All other domains (`auth`, `tenant`, `rpt`, `txn`) use **split layout**: `models/`, `schemas/`, `services/` subpackages.
- Never keep both `models.py` and `models/` under the same domain — Python resolves one `models` name only.

---

## Models — SQLAlchemy 2.0

```python
from mtf.shared.database import Base
from sqlalchemy import VARCHAR, text
from sqlalchemy.orm import Mapped, mapped_column

class MyEntity(Base):
    __tablename__ = "my_entity"
    __table_args__ = {"schema": "domain_name"}

    id: Mapped[str] = mapped_column(VARCHAR(26), primary_key=True)
```

- Use `Mapped[T]` and `mapped_column()` for all columns.
- Use `T | None` in `Mapped` for nullable columns: `Mapped[str | None]`.
- Set `__table_args__ = {"schema": "<domain>"}` on every model.
- Set `__tablename__` explicitly — always **singular** (`app_user`, `tenant`, `tenant_account`).
- Server-side defaults: `server_default=text("...")` or `server_default=FetchedValue()` — never Python-side defaults for DB-managed values.
- All IDs: `VARCHAR(26)` — ULID format.

### ROWVERSION (optimistic concurrency)

```python
from sqlalchemy.dialects.mssql import ROWVERSION
from sqlalchemy.schema import FetchedValue

row_version: Mapped[bytes] = mapped_column(
    ROWVERSION,
    nullable=False,
    server_default=FetchedValue(),
)
```

### Computed column (email_normalized on AppUser)

```python
from sqlalchemy import Computed

email_normalized: Mapped[str] = mapped_column(
    VARCHAR(255),
    Computed("LOWER(LTRIM(RTRIM(email)))", persisted=True),
)
```

---

## Schemas — Pydantic v2

Follow the `Create / Update / Read` naming pattern:

| Class | Used for | Notes |
|-------|----------|-------|
| `XxxCreate` | POST request body | Required fields only; `id` generated in service |
| `XxxUpdate` | PATCH request body | All fields optional (`T \| None`); must include `row_version` |
| `XxxRead` | All responses | `model_config = ConfigDict(from_attributes=True)` required |

```python
from pydantic import BaseModel, ConfigDict

class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
```

### row_version JSON encoding

`row_version` is `bytes` in Python — use **base64 strings** in JSON request/response bodies.

```python
import base64
from pydantic import BaseModel, ConfigDict, field_validator

# On XxxRead — serialize bytes to base64 in JSON responses
class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, ser_json_bytes="base64")
    row_version: bytes
    id: str
    name: str

# On XxxUpdate — accept base64 string in PATCH body, validate to bytes
class TenantUpdate(BaseModel):
    row_version: bytes
    name: str | None = None

    @field_validator("row_version", mode="before")
    @classmethod
    def decode_row_version(cls, v: object) -> bytes:
        if isinstance(v, bytes):
            return v
        if isinstance(v, str):
            return base64.b64decode(v, validate=True)
        raise ValueError("row_version must be a base64-encoded string")
```

Alternatively, define a shared `RowVersionField` type in `mtf/shared/schemas.py` and reuse it on all `XxxUpdate` / `XxxRead` schemas.

### Never expose

Never include `password_hash` or `mfa_secret_enc` in any `Read` schema.

---

## Standard Columns

Every mutable table includes:

| Column | Type | Purpose |
|--------|------|---------|
| `is_active` | `BIT NOT NULL DEFAULT 1` | Business-level active flag |
| `is_deleted` | `BIT NOT NULL DEFAULT 0` | Soft-delete flag |
| `row_version` | `ROWVERSION NOT NULL` | Optimistic concurrency |
| `created_at` | `DATETIME2(3) NOT NULL DEFAULT sysutcdatetime()` | Creation timestamp (UTC) |
| `updated_at` | `DATETIME2(3) NOT NULL DEFAULT sysutcdatetime()` | Last update timestamp (UTC) |
| `created_by` | `VARCHAR(26) NULL → auth.app_user.id` | Who created the row |
| `updated_by` | `VARCHAR(26) NULL → auth.app_user.id` | Who last updated the row |
| `deleted_by` | `VARCHAR(26) NULL → auth.app_user.id` | Who soft-deleted the row |

`audit.audit_log` is **append-only** — no `updated_at`, no `row_version`, no soft-delete columns. Live shape: [../sql/audit_schema_v2.sql](../sql/audit_schema_v2.sql). `deevo_app` may `SELECT` and `INSERT` only (`DENY UPDATE, DELETE`).

---

## Identifiers

- **Primary keys:** ULID stored as `VARCHAR(26)`.
- **Generate in service:** `from python_ulid import ULID; id = str(ULID())`
- **Rationale:** Lexicographically sortable by creation time, URL-safe, non-sequential.

---

## Soft Deletes

- Never hard-delete rows from mutable tables.
- Soft delete: set `is_deleted = True`, `deleted_by = current_user.id`, `is_active = False`.
- Every `SELECT` must filter `Model.is_deleted.is_(False)` unless explicitly querying deleted records.
- Expose `DELETE /resource/{id}` endpoint that performs the soft delete → returns `204 No Content`.

---

## Optimistic Concurrency

- Client sends `row_version` (base64) in PATCH request body.
- Service fetches current row, compares `row_version` bytes.
- Mismatch → raise `409 Conflict` with code `<DOMAIN>_<ENTITY>_CONFLICT`.
- On successful update, SQL Server auto-increments `row_version` — refresh and return updated value in response.

---

## Date and Time

- All date/time columns: `DATETIME2(3)` (millisecond precision, UTC).
- SQLAlchemy mapping: `DateTime(timezone=False)` — treat all naive datetimes as UTC.
- Server defaults: `server_default=text("sysutcdatetime()")`.
- In Python services/helpers: `datetime.now(timezone.utc)` — normalize to naive UTC before assigning to model fields.

---

## Authentication & JWT

- **Mechanism:** Bearer token in `Authorization: Bearer <token>` header.
- **Access token:** Short-lived (`DEEVO_JWT_ACCESS_TOKEN_EXPIRE_MINUTES`).
- **Refresh token:** Long-lived (`DEEVO_JWT_REFRESH_TOKEN_EXPIRE_DAYS`).
- **Algorithm:** `HS256` (`DEEVO_JWT_ALGORITHM`).
- **Secret:** `DEEVO_JWT_SECRET_KEY` — `"changeme"` must never be used in production.
- **Crypto helpers:** `mtf/shared/security.py` — bcrypt hashing, JWT create/decode, SHA-256 digest, ULID generation.
- **bcrypt pin:** `bcrypt>=4.0.1,<4.1` — passlib 1.7.4 is incompatible with bcrypt 4.1+.

### Token Storage

Tokens are **never stored raw** in the database:

| Token | Stored as |
|-------|----------|
| `session.token_hash` | `SHA-256(access_token)` as `BINARY(32)` |
| `session.refresh_token_hash` | `SHA-256(refresh_token)` as `BINARY(32)` |
| `tenant_user.invite_token_hash` | `SHA-256(invite_token)` as `BINARY(32)` |
| `tenant_account_user.invite_token_hash` | `SHA-256(invite_token)` as `BINARY(32)` |

### Access JWT Payload

```json
{
  "user_id": "...",
  "user_type": "system | tenant | tenant_account",
  "user_scope": "system | tenant | tenant_account",
  "tenant_id": "... or null",
  "exp": 1234567890,
  "jti": "..."
}
```

### Refresh JWT Payload

```json
{
  "user_id": "...",
  "session_id": "...",
  "exp": 1234567890,
  "jti": "..."
}
```

### Public Routes (no auth required)

```
GET  /health
POST /api/auth/login
POST /api/auth/refresh
```

### Refresh Token Rotation

On refresh, update the **existing** `auth.session` row with a new `refresh_token_hash`. Do **not** create a new session row.

---

## User Scope

Every `auth.app_user` has a `user_scope` that determines which application they can access:

| `user_scope` | Application | Created by |
|-------------|------------|-----------|
| `system` | `deevo_admin` (Streamlit, port 8501) | Seed script only |
| `tenant` | `deevo_crm` (React, port 3000) | Tenant owner/admin |
| `tenant_account` | `deevo_portal` (React, port 3001) | Tenant staff or account admin |

- Services must validate `user_scope` matches the expected scope for the endpoint.
- `get_current_user` (in `mtf/shared/deps.py`) decodes the token and returns `TokenContext` including `user_scope`.
- Services must **never** trust `tenant_id` from the request body — always use value from the authenticated token context.

### RBAC (v1)

v1 authorisation is **scope-based only** via `require_scope(...)` on endpoints (`system`, `tenant`, `tenant_account`). Fine-grained roles/permissions tables are **not** in v1 — add a dedicated RBAC section here when introduced.

---

## User Type

`user_type` identifies who is performing an action. Used in `auth.session` and `audit.audit_log`:

| `user_type` | Who | Logs into |
|------------|-----|----------|
| `system` | Platform owner (Deevo team) | `deevo_admin` |
| `tenant` | Tenant's internal staff | `deevo_crm` |
| `tenant_account` | Tenant's account portal user | `deevo_portal` / `deevo_account_st` |

`user_type` and `user_scope` always carry the same value for a given user. Both fields exist for clarity at the boundary — `user_scope` is about application access, `user_type` is about audit identity.

---

## Dependencies (FastAPI)

All dependencies declared in `mtf/shared/deps.py`:

```python
# Inject authenticated user identity
current_user: TokenContext = Depends(get_current_user)

# Enforce scope
_: TokenContext = Depends(require_scope("system"))
_: TokenContext = Depends(require_scope("tenant", "system"))

# Pagination
pagination: PaginationParams = Depends(get_pagination)

# DB session
db: Session = Depends(get_db)
```

---

## Pagination

All list endpoints:

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `skip` | `int` | `0` | `>= 0` | Rows to skip |
| `limit` | `int` | `100` | `1–200` | Max rows (hard cap 200) |

Services apply `.offset(pagination.skip).limit(pagination.limit)` on every list query.

---

## HTTP Methods and Status Codes

| Method | Action | Success |
|--------|--------|---------|
| `POST` | Create | `201 Created` |
| `GET` | Fetch single or list | `200 OK` |
| `PATCH` | Partial update | `200 OK` |
| `DELETE` | Soft delete | `204 No Content` |

| Status | When |
|--------|------|
| `400` | Malformed request Pydantic doesn't catch |
| `401` | Missing or invalid token |
| `403` | Authenticated but not authorised |
| `404` | Not found or soft-deleted |
| `409` | Optimistic concurrency conflict |
| `422` | Pydantic validation failure (automatic) |

---

## Error Responses

```python
raise HTTPException(
    status_code=404,
    detail={"code": "AUTH_USER_NOT_FOUND", "message": "User not found"},
)
```

- `code`: `DOMAIN_ENTITY_REASON` in SCREAMING_SNAKE_CASE.
- `code` values are **stable** — frontends and integrations depend on them.
- `message` is human-readable.

### Example Codes

| Code | Status |
|------|--------|
| `AUTH_USER_NOT_FOUND` | 404 |
| `AUTH_USER_CONFLICT` | 409 |
| `AUTH_INVALID_TOKEN` | 401 |
| `AUTH_FORBIDDEN` | 403 |
| `TENANT_TENANT_NOT_FOUND` | 404 |
| `TENANT_ACCOUNT_CONFLICT` | 409 |
| `TENANT_ACCOUNT_DUPLICATE_ACCOUNT_CODE` | 409 |
| `AUDIT_LOG_NOT_FOUND` | 404 |

---

## JSON Field Names

All JSON request and response fields use `snake_case`. No `camelCase` aliases.

---

## Audit Logging

Canonical DDL: [../sql/audit_schema_v2.sql](../sql/audit_schema_v2.sql) (already applied on `deevo_app_dev2`). One row per event in `audit.audit_log`. No HTTP method, path, or body columns — `request_id` correlates several writes from the same call.

Every service method that performs `INSERT`, `UPDATE`, or soft-`DELETE` on any resource must write an entry in the **same transaction** as the mutation. Auth events (`login`, `login_failed`, `logout`) must also be logged. `access_denied` / `export` / `import` when those events occur.

Do not put foreign keys on this table — history must outlive users and tenants. `deevo_app` cannot `UPDATE` or `DELETE` rows.

### Columns

| Field | Value |
|-------|-------|
| `tenant_id` | From token context (null for system-wide actions and some failed logins) |
| `account_id` | From token context when the actor is `tenant_account` (portal account) |
| `session_id` | From `auth.session` via the access-token hash (`get_audit_source`). Null on login / login_failed (no Bearer yet); login/logout still set it in `SessionService` |
| `request_id` | ULID generated by this backend for the HTTP request — never inbound `X-Request-ID` or trace headers |
| `user_id` | From token context (null when the actor is unknown, e.g. failed login with unknown email) |
| `user_type` | `"system"` \| `"tenant"` \| `"tenant_account"` |
| `schema_name` | SQL schema of the affected table (e.g. `"tenant"`). Required for data-change actions |
| `table_name` | Table name (e.g. `"tenant_account"`). Required for data-change actions |
| `record_id` | ULID of the affected row. Required for data-change actions |
| `action` | See actions below |
| `old_values` / `new_values` | JSON **objects** (`ISJSON(..., OBJECT)`). See JSON rules |
| `ip_address` | From the request |
| `user_agent` | From the request |
| `reason` | Optional human-readable reason |

Data-change actions (`insert`, `update`, `delete`, `restore`) must set `schema_name`, `table_name`, and `record_id`. Auth and security actions may leave those null.

### Actions

| `action` | When |
|----------|------|
| `insert` | New row |
| `update` | In-place field changes (not soft delete) |
| `delete` | Soft delete (`is_deleted` flags in old/new) or hard delete (`new_values` null) |
| `restore` | Undelete |
| `login` | Successful login |
| `login_failed` | Failed login |
| `logout` | Logout |
| `access_denied` | Authorization failure you choose to record |
| `export` | Export |
| `import` | Import |

Always use **`delete`** for soft delete. Do not log the same soft-delete as `update`.

### JSON rules

| Action | `old_values` | `new_values` |
|--------|--------------|--------------|
| `insert` | null | full row snapshot |
| `update` / `restore` | required; same keys as new | required; changed fields only on `update` |
| `delete` (soft) | required | required; soft-delete flag changes |
| `delete` (hard) | full row snapshot | null |

Never store `password`, `password_hash`, `token_hash`, `refresh_token_hash`, `invite_token_hash`, mailbox OAuth tokens, or any other secret, token, or API key. `login_failed` may store email, never password.

### Writers

`append_audit_log` adds a row and never commits — the mutation service owns the transaction. Data-change helpers: `audit_insert`, `audit_update` (no row when nothing changed), `audit_soft_delete`. Mutation APIs pass `CurrentUser` as `actor` and `AuditSource` from `get_audit_source` (fills `session_id` from `auth.session` when the request has a Bearer token). Do not audit reads, report `/run`, txn screen GET, or mailbox credential/token writes. Tenant create sets `tenant_id` to the new tenant; account mutations set `tenant_id` and `account_id` to the account row.

---

## CORS

```python
# .env
DEEVO_ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:3001","http://localhost:8501","http://localhost:8502"]
```

`CORSMiddleware` must be added in `main.py` before any routers.

---

## Database Connectivity

- Application connects as `deevo_app` — read/write only, no DDL.
- Migrations run as `deevo_ddl` — separate credentials, never used by the running app.
- All credentials via `.env` only — never committed.
- Config surface: `DEEVO_*` env vars via `mtf/shared/config.py` (loaded via `pydantic-settings`).

### Session lifecycle

- `get_db` in `mtf/shared/deps.py` yields a **request-scoped** `Session`.
- **One transaction per request:** commit on success, rollback on unhandled exception, always close the session.
- **Services do not commit** — the dependency (or a thin unit-of-work wrapper) owns `commit()` / `rollback()`.
- Services may call `db.flush()` when generated IDs are needed before commit.
- Audit log writes for a mutation belong in the **same transaction** as the mutation.

### Schema changes (SSMS — v1)

For **`deevo_mt_framework_backend`**, table DDL is **owned and applied in SQL Server Management Studio**, not via Alembic in this repo.

- Create/alter tables in schemas `auth`, `tenant`, `audit`, `rpt`, `txn` using **`deevo_ddl`** (or equivalent DDL login). Canonical DDL: [../sql/database_schema_v1.sql](../sql/database_schema_v1.sql) for `auth`/`tenant`, [../sql/audit_schema_v2.sql](../sql/audit_schema_v2.sql) for `audit.audit_log`, [../sql/rpt_schema_v5.sql](../sql/rpt_schema_v5.sql) for `rpt`, [../sql/txn_schema_v2.sql](../sql/txn_schema_v2.sql) for `txn` (and V2 report permission/action tables).
- SQLAlchemy models in `mtf/**/models` must match the live database — update models when SSMS schema changes.
- Keep a change script in source control (e.g. `docs/sql/` or your team’s script folder) if you want history; the app does not run DDL.
- Product schemas (`crm`, etc.) are managed by their own backends.

Alembic remains in `pyproject.toml` for optional future use; it is **not** the v1 workflow for MTF.

### Shared database across services

Products share the SQL Server instance but **must not write** to `auth`, `tenant`, or `audit` tables except through this service (or documented cross-service exceptions). Coordinate SSMS script order when MTF and a product both change schema in the same release.

---

## Bootstrap / Seed User

A system-scope seed user is required for the framework to function. Created once via SQL:

```
id:         01HYSTEM00000000000000000
email:      admin@example.com
user_scope: system
created_by: 01HYSTEM00000000000000000  (self-referencing)
```

Password hash: use the same helper as runtime (`hash_password` in `mtf/shared/security.py`, backed by passlib+bcrypt):

```bash
uv run python -c "from mtf.shared.security import hash_password; print(hash_password('your_password'))"
```

---

## Tests (pytest)

```
tests/
  conftest.py       ← TestClient, DB session factory, shared fixtures
  auth/
  tenant/
  audit/
```

- **Integration tests:** Require live SQL Server. Mark with `@pytest.mark.integration`.
- **Skip integration tests:** `DEEVO_SKIP_DB_TESTS=1` or `pytest -m "not integration"`.
- **API tests:** `httpx.AsyncClient` / `TestClient`.
- **Unit tests:** Test service functions directly with an explicit `Session` or stubs.

---

## Configuration Reference (.env)

Canonical names — must match [`.env.example`](../.env.example) and `mtf/shared/config.py`:

```bash
# App
DEEVO_APP_NAME=Deevo MT Framework
DEEVO_DEBUG=false
DEEVO_ENVIRONMENT=development

# Database (runtime user: deevo_app)
DEEVO_MSSQL_SERVER=localhost
DEEVO_MSSQL_PORT=1433
DEEVO_MSSQL_DATABASE=deevo_mt
DEEVO_MSSQL_USER=deevo_app
DEEVO_MSSQL_PASSWORD=change-me
DEEVO_MSSQL_ODBC_DRIVER=ODBC Driver 17 for SQL Server
DEEVO_MSSQL_URL_MINIMAL=true
DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE=true

# JWT
DEEVO_JWT_SECRET_KEY=change-me
DEEVO_JWT_ALGORITHM=HS256
DEEVO_JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
DEEVO_JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS (JSON array)
DEEVO_ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:3001","http://localhost:8501","http://localhost:8502"]

# Tests — set to 1 to skip integration tests without SQL Server
DEEVO_SKIP_DB_TESTS=0
```

---

## Package Conventions

- `__init__.py` under `mtf/`, `mtf/shared/`, and every `mtf/<domain>/`.
- `api/__init__.py` composes and exports `router` from entity modules.
- `models/__init__.py` re-exports ORM classes.
- `schemas/__init__.py` re-exports Create/Update/Read types.
- `services/__init__.py` re-exports service classes.
- New entity: add `models/<entity>.py`, `schemas/<entity>.py`, `services/<entity>.py`, then update the three `__init__.py` files.

---

*Last updated: May 2026 — v1.1 for deevo_mt_framework_backend. Supersedes the conventions doc previously used in deevo_crm_backend.*