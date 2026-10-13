---
name: mtf-add-api-endpoint
description: >-
  Adds a new MTF HTTP endpoint following api → services → models layering. Use when
  creating routes, CRUD for auth/tenant/audit entities, new API modules, or nested
  tenant resources like POST /api/tenant/{id}/users.
disable-model-invocation: true
---

# MTF Add API Endpoint

Read [docs/CONVENTIONS.md](../../../docs/CONVENTIONS.md) (API, Layering, Errors) and [docs/PROJECT_CONTEXT.md](../../../docs/PROJECT_CONTEXT.md) (scope, mount points).

## Scope check

In scope: `mtf/auth`, `mtf/tenant`, `mtf/audit`, `mtf/rpt`, `mtf/txn`, `mtf/shared`.

Out of scope: product entity CRUD (`crm` Lead, etc.), `email`, `scout`, `flow`. `mtf/txn` is generic screen metadata only.

## Checklist

```
- [ ] 1. Pydantic schemas (Create, Read, Update as needed)
- [ ] 2. Service methods (business logic, ULIDs, soft delete, errors)
- [ ] 3. API router module (HTTP only — Depends, status codes, response_model)
- [ ] 4. Register router in mtf/<domain>/api/__init__.py (static paths before param routes)
- [ ] 5. Export schemas in mtf/<domain>/schemas/__init__.py if new public types
- [ ] 6. Unit tests (service or API with mocks)
- [ ] 7. Integration test if endpoint hits live DB (pytestmark = pytest.mark.integration)
- [ ] 8. DEEVO_SKIP_DB_TESTS=1 uv run pytest -m "not integration" -v
```

## Layering rules

| Layer | Responsibility |
|-------|----------------|
| `api/` | Routing, `Depends`, HTTP status, call service, `raise_if_not_found` |
| `services/` | Validation, ULID generation, queries, commits, `conflict`/`not_found` |
| `models/` | SQLAlchemy mappings only |

**Never** put SQL queries or business rules directly in `api/` handlers.

## Error shape

Use helpers from `mtf.shared.exceptions`:

```python
from mtf.shared.exceptions import conflict, not_found, bad_request, raise_if_not_found

conflict("TENANT", "Subdomain already exists")       # → 409 TENANT_CONFLICT
not_found("TENANT_USER", "Membership not found")     # → 404 TENANT_USER_NOT_FOUND
bad_request("TENANT_USER", "Invalid role")             # → 400 TENANT_USER_BAD_REQUEST
```

Stable `code` values — frontends depend on them. See CONVENTIONS error catalog.

## Auth on routes

Import from `mtf.shared.deps`:

- `require_scope("system")` — platform admin routes
- `require_scope("tenant")` — tenant-scoped staff routes
- `get_current_user` — read caller context

Public (no Bearer): `GET /health`, `POST /api/auth/login`, `POST /api/auth/refresh`.

## Router registration

**auth** — [mtf/auth/api/__init__.py](../../../mtf/auth/api/__init__.py): compose entity routers into one `router`.

**tenant** — [mtf/tenant/api/__init__.py](../../../mtf/tenant/api/__init__.py): static paths (e.g. staff) **before** `/{tenant_id}` routes.

**audit** — flat [mtf/audit/api/audit_log.py](../../../mtf/audit/api/audit_log.py); append-only (no update/delete).

App mounts in [main.py](../../../main.py):

```python
app.include_router(auth_router, prefix="/api/auth")
app.include_router(tenant_router, prefix="/api/tenant")
app.include_router(audit_router, prefix="/api/audit")
```

## Service pattern (sketch)

```python
from ulid import ULID

class TenantFooService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, payload: TenantFooCreate) -> TenantFoo:
        row = TenantFoo(id=str(ULID()), ...)
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def list_active(self, tenant_id: str, skip: int = 0, limit: int = 100) -> list[TenantFoo]:
        return list(
            self._db.scalars(
                select(TenantFoo).where(
                    TenantFoo.tenant_id == tenant_id,
                    TenantFoo.is_deleted.is_(False),
                ).offset(skip).limit(limit)
            )
        )
```

## API pattern (sketch)

```python
router = APIRouter()

def get_foo_service(db: Session = Depends(get_db)) -> TenantFooService:
    return TenantFooService(db)

@router.post("/foos", response_model=TenantFooRead, status_code=status.HTTP_201_CREATED)
def create_foo(
    payload: TenantFooCreate,
    _current: CurrentUser = Depends(require_scope("system")),
    service: TenantFooService = Depends(get_foo_service),
) -> TenantFooRead:
    return service.create(payload)
```

## Integration test pattern

Follow [tests/tenant/test_tenant_user_api_integration.py](../../../tests/tenant/test_tenant_user_api_integration.py):

- `pytestmark = pytest.mark.integration`
- `_skip_if_disabled()` checks `DEEVO_SKIP_DB_TESTS`
- Unique emails/subdomains via `uuid`
- `try` / `finally` cleanup with soft-delete
- Stub `get_current_user` via `app.dependency_overrides` when testing as system user

## Module layout reference

| Domain | Split layout | Flat layout |
|--------|--------------|-------------|
| auth, tenant | `api/`, `models/`, `schemas/`, `services/` per entity | — |
| audit | — | `models.py`, `schemas.py`, `service.py`, `api/audit_log.py` |
