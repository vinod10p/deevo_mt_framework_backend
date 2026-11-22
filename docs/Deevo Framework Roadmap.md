# Deevo Framework Roadmap

Nov 21, 2026 · @vinod

## Summary

Finish roles and permissions first, then build what a second application needs before adding more features. The order is: Phase 0 closes open work, Phase 1 makes the framework reusable, and Phases 2 to 4 add security, shared platform services and operations. Three open questions at the end decide the order within those phases.

The same plan is laid out visually on the [roadmap whiteboard](https://claude.ai/artifact/8vb3wtqyNF5w5bTA2RWisT).

## Where we are

The core of the framework works, and the dynamic menu is finished. Roles and permissions are the main open item.

| Area | Status | Notes |
| --- | --- | --- |
| Login, auth, sessions | Built | Core of the framework |
| Multi-tenant user model | Built | `app_user`, `tenant_user`, `tenant_account_user` |
| Generic reports | Built | Role-based report access replaces `rpt.report_permission` |
| Audit log | Built | Logs login/logout and screen updates only. Inserts, deletes, failed logins and access denials are not logged yet |
| Dynamic menu | Done | Database-driven |
| Roles and permissions | In progress | Schema v3 is final. Grants only, many roles per user, read-only platform template roles |
| License | Done | MIT, Deevolight LLC |

## Phase 0: Finish open work

Close out roles and permissions before starting anything new, because almost every later feature checks permissions.

- [ ] **RBAC backend:** Python models, permission resolver and `require_permission`, proven end to end on reports first
- [ ] **Seed script:** idempotent seed of screen permissions, template roles and default report grants, using fixed IDs
- [ ] **Backfill:** map existing `tenant_user.role` values to `user_role` and copy default report grants for each existing tenant
- [ ] **Tenant role-admin screen:** tenant admins assign roles and copy a template into a custom role. Keep the last-admin rule safe under concurrent edits
- [ ] **Audit gaps:** log inserts, deletes, restores, failed logins and access denials. Denials become easy to log once the resolver exists

## Phase 1: Reusable by a second app

This phase turns the codebase into a framework that a second application can adopt without copying code.

1. **Tenant management and feature flags:** tenant onboarding and provisioning, tenant settings, and modules switched on or off per tenant. A module that is off hides its menu items and permissions for that tenant.
2. **Layered settings:** platform default, then tenant override, then user override. Most later features read their configuration from here.
3. **User lifecycle:** invite, activate and deactivate, password reset, and lockout after repeated failed logins.
4. **Generic CRUD base:** a shared base for data entry screens with validation, soft delete, rowversion concurrency, and built-in audit and permission checks.
5. **Lookups and document numbering:** shared code tables with per-tenant overrides, and per-tenant number sequences such as `INV-2026-00045`.

## Phase 2: Security

Harden access once RBAC is proven. Move SSO into Phase 1 if a customer needs it to sign.

- **Service accounts and API keys:** the deferred `service` user type, for agents and background jobs. Uses the RBAC resolver, so the same permissions apply.
- **MFA, then SSO:** TOTP-based MFA first, then OIDC (Entra ID, Google). Add SAML only if a customer asks for it.
- **Rate limiting:** per tenant and per user, applied first to login and public APIs.
- **Secrets in Azure Key Vault:** no connection strings or keys in config files.
- **SQL Server row-level security:** a backstop behind the app-level tenant filter, so a missed `WHERE tenant_id` cannot leak another tenant's data.

## Phase 3: Platform services

Build the job scheduler first, because notifications, report scheduling, retention and large imports all run as jobs.

1. **Background jobs and scheduler:** queued and scheduled jobs that know which tenant they belong to, with retries and job history.
2. **Notifications:** email templates per tenant (SMS later), sent as jobs.
3. **File storage:** Azure Blob, with one container or path prefix per tenant.
4. **Import and export:** CSV and Excel, built on the CRUD base and run as jobs, with an audit entry for each run.
5. **Permission and menu caching:** cache each user's resolved permissions and menu, and clear the cache when roles or grants change.

## Phase 4: Operations

This phase makes the framework easier to run, support and charge for in production.

- **Retention and audit archiving:** a scheduled job that moves old audit rows to an archive, replacing the manual process planned for version one.
- **Health checks, logging and tracing:** health endpoints, plus structured logs keyed by the existing `request_id` ULID so a request can be traced across services.
- **API versioning:** versioned routes, so applications built on the framework can upgrade on their own schedule.
- **Usage metering per tenant:** count API calls, reports run, storage and active users. Billing depends on this, so add the hooks earlier if billing is planned.

## Later

Wait until an application actually needs these. Each is large, and the right design depends on that application's requirements.

- **Workflow and approvals:** configurable approval steps, for example for purchase orders or discounts.
- **Localization:** multiple languages, time zones and currencies.
- **Subscription and billing:** plans and invoicing, built on usage metering.

## Key dependencies

&#91;embedded content: feature dependencies · 4 foundations\]

RBAC is the only foundation in progress now. Import and export needs both the CRUD base and the job scheduler, so it cannot start until both exist.

## Open questions

Answering these three settles the order of work within Phases 1 to 3.

- [ ] **Which application adopts the framework first: DeevoAgent, the jewelry ERP, or a new one?** That application's needs set the order inside Phase 1.
- [ ] **Do any customers need SSO soon?** If so, move OIDC SSO into Phase 1.
- [ ] **Will tenants be billed by usage?** If so, add metering hooks in Phase 1. Retrofitting them later means revisiting every feature.
