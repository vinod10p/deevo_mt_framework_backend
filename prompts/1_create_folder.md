Create the following folder structure for a new Python project 
called deevo_mt_framework_backend. Use uv as the package manager.

The main package folder is named mtf (Deevo Multi-Tenant Framework).

Create this exact structure:

deevo_mt_framework_backend/
├── mtf/
│   ├── __init__.py
│   ├── shared/
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
│   │   │   ├── __init__.py
│   │   │   ├── session.py
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
│   └── audit/
│       ├── __init__.py
│       ├── api/
│       │   ├── __init__.py
│       │   └── audit_log.py
│       ├── models.py
│       ├── schemas.py
│       └── service.py
├── main.py
├── docs/
├── prompts/
├── tests/
│   ├── conftest.py
│   ├── auth/
│   │   └── __init__.py
│   ├── tenant/
│   │   └── __init__.py
│   └── audit/
│       └── __init__.py
├── third_party_licenses/
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md

Rules:
- All .py files except __init__.py should contain only: # TODO
- All __init__.py files should be empty
- Do not write any logic yet
- Create the structure exactly as shown