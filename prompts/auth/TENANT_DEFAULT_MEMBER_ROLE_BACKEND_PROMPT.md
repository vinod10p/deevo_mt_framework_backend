# Backend prompt — Per-user default Member permissions

**SUPERSEDED.** Do not implement this prompt.

Membership is now **`admin` | `member` only** (`sql/rbac_fix_05_admin_member_only.sql`):

- `admin` → thin platform `tenant_admin` (Role Admin + admin menus)
- `member` → **no** automatic `tenant_member` template
- Product access comes only from **assigned custom roles**
- The `default_member_role_enabled` column remains in the schema for history but is **ignored** by dual-write; the HTTP switch was removed from tenant Role Admin routes

See [`ROLE_ADMIN_FRONTEND_PROMPT.md`](ROLE_ADMIN_FRONTEND_PROMPT.md) and
[`DEEVOFLOW_TENANT_ROLE_ADMIN.md`](DEEVOFLOW_TENANT_ROLE_ADMIN.md) for the current model.
