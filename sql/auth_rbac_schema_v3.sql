/*
auth_rbac_schema_v3.sql
RBAC tables for the multi-tenant framework (v3).

Identity and membership (existing, not created here):
  auth.app_user, auth.tenant_user, auth.tenant_account_user

New tables:
  auth.permission, auth.role, auth.role_permission, auth.user_role,
  auth.role_report, auth.default_role_report

Apply in SSMS as deevo_ddl on deevo_app_dev2. If GRANT fails, run the GRANT
block as dbo. Runtime user deevo_app is SELECT/INSERT/UPDATE/DELETE on these
tables (they are mutable catalogs, not append-only audit).

Do not uncomment DROP txn.screen_permission — DeevoFlow Lead still uses it.
*/

USE [deevo_app_dev2];
GO

/* =========================================================================
   RBAC for the multi-tenant framework  (v3)

   v3 changes:
     - role_report: tenant_id NOT NULL, is_active added, unique key includes tenant_id,
       FK to rpt.report_definition
     - default_role_report added (defaults are copied per tenant at onboarding)
     - role_permission: standard soft-delete columns, filtered unique index
     - user_scope enforced by composite FKs on role_permission and user_role
     - user_role: tenant_id is column 2; scope/tenant/account shape check; index cleanup
     - role: platform roles must be is_system = 1
     - every table: CK_<table>_deleted soft-delete integrity check
     - constraint names follow UQ_ / FK_<table>_<column>
   ========================================================================= */


/* =========================================================================
   0. Superkey on app_user so user_role can enforce user_scope by FK.
      (id is already unique; this adds no new rule, only an FK target.)
   ========================================================================= */
IF NOT EXISTS (SELECT 1 FROM sys.key_constraints
               WHERE name = 'UQ_app_user_id_user_scope'
                 AND parent_object_id = OBJECT_ID('auth.app_user'))
    ALTER TABLE [auth].[app_user]
        ADD CONSTRAINT [UQ_app_user_id_user_scope] UNIQUE ([id], [user_scope]);
GO


/* =========================================================================
   1. permission: global catalog of everything that can be granted.
      code = '<resource_type>.<resource_code>.<action>', e.g. 'screen.customer.update'
   ========================================================================= */
CREATE TABLE [auth].[permission](
    [id]            varchar(26)   NOT NULL,
    [code]          varchar(150)  NOT NULL,
    [resource_type] varchar(20)   NOT NULL,     -- menu | screen | api
    [resource_code] varchar(100)  NOT NULL,     -- e.g. 'customer', 'settings.users'
    [action]        varchar(20)   NOT NULL,     -- view | create | update | delete | export | import | approve
    [user_scope]    varchar(20)   NOT NULL,     -- system | tenant | tenant_account
    [description]   nvarchar(300) NULL,
    [is_active]     bit           NOT NULL CONSTRAINT [DF_permission_is_active]  DEFAULT (1),
    [is_deleted]    bit           NOT NULL CONSTRAINT [DF_permission_is_deleted] DEFAULT (0),
    [row_version]   rowversion    NOT NULL,
    [created_at]    datetime2(3)  NOT NULL CONSTRAINT [DF_permission_created_at] DEFAULT (sysutcdatetime()),
    [updated_at]    datetime2(3)  NOT NULL CONSTRAINT [DF_permission_updated_at] DEFAULT (sysutcdatetime()),
    [created_by]    varchar(26)   NULL,
    [updated_by]    varchar(26)   NULL,
    [deleted_at]    datetime2(3)  NULL,
    [deleted_by]    varchar(26)   NULL,
    CONSTRAINT [PK_permission] PRIMARY KEY CLUSTERED ([id]),
    CONSTRAINT [UQ_permission_id_user_scope] UNIQUE ([id], [user_scope]),       -- composite FK target
    CONSTRAINT [CK_permission_resource_type] CHECK ([resource_type] IN ('menu','screen','api')),
    CONSTRAINT [CK_permission_action]        CHECK ([action] IN ('view','create','update','delete','export','import','approve')),
    CONSTRAINT [CK_permission_user_scope]    CHECK ([user_scope] IN ('system','tenant','tenant_account')),
    CONSTRAINT [CK_permission_deleted]       CHECK ([is_deleted] = 0 OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL)),
    CONSTRAINT [FK_permission_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_permission_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_permission_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user]([id])
);
GO

CREATE UNIQUE INDEX [UQ_permission_code]
    ON [auth].[permission]([code]) WHERE [is_deleted] = 0;
GO


/* =========================================================================
   2. role: a named bundle of permissions.
      tenant_id NULL = platform role (template or system staff), always locked.
      tenant_id set  = role a tenant created for itself.
   ========================================================================= */
CREATE TABLE [auth].[role](
    [id]          varchar(26)   NOT NULL,
    [tenant_id]   varchar(26)   NULL,
    [code]        varchar(50)   NOT NULL,
    [name]        nvarchar(100) NOT NULL,
    [description] nvarchar(300) NULL,
    [user_scope]  varchar(20)   NOT NULL,
    [is_system]   bit           NOT NULL CONSTRAINT [DF_role_is_system]  DEFAULT (0),
    [is_active]   bit           NOT NULL CONSTRAINT [DF_role_is_active]  DEFAULT (1),
    [is_deleted]  bit           NOT NULL CONSTRAINT [DF_role_is_deleted] DEFAULT (0),
    [row_version] rowversion    NOT NULL,
    [created_at]  datetime2(3)  NOT NULL CONSTRAINT [DF_role_created_at] DEFAULT (sysutcdatetime()),
    [updated_at]  datetime2(3)  NOT NULL CONSTRAINT [DF_role_updated_at] DEFAULT (sysutcdatetime()),
    [created_by]  varchar(26)   NULL,
    [updated_by]  varchar(26)   NULL,
    [deleted_at]  datetime2(3)  NULL,
    [deleted_by]  varchar(26)   NULL,
    CONSTRAINT [PK_role] PRIMARY KEY CLUSTERED ([id]),
    CONSTRAINT [UQ_role_id_user_scope] UNIQUE ([id], [user_scope]),             -- composite FK target
    CONSTRAINT [CK_role_user_scope]          CHECK ([user_scope] IN ('system','tenant','tenant_account')),
    CONSTRAINT [CK_role_system_scope_tenant] CHECK ([user_scope] <> 'system' OR [tenant_id] IS NULL),
    CONSTRAINT [CK_role_platform_is_system]  CHECK ([tenant_id] IS NOT NULL OR [is_system] = 1),
    CONSTRAINT [CK_role_deleted]             CHECK ([is_deleted] = 0 OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL)),
    CONSTRAINT [FK_role_tenant_id]  FOREIGN KEY ([tenant_id])  REFERENCES [tenant].[tenant]([id]),
    CONSTRAINT [FK_role_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_role_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_role_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user]([id])
);
GO

CREATE UNIQUE INDEX [UQ_role_tenant_code]
    ON [auth].[role]([tenant_id], [code]) WHERE [tenant_id] IS NOT NULL AND [is_deleted] = 0;
CREATE UNIQUE INDEX [UQ_role_platform_code]
    ON [auth].[role]([code])              WHERE [tenant_id] IS NULL     AND [is_deleted] = 0;
GO


/* =========================================================================
   3. role_permission: which permissions a role grants.
      user_scope + composite FKs: a role can only grant permissions of its own scope.
   ========================================================================= */
CREATE TABLE [auth].[role_permission](
    [id]            varchar(26)  NOT NULL,
    [role_id]       varchar(26)  NOT NULL,
    [permission_id] varchar(26)  NOT NULL,
    [user_scope]    varchar(20)  NOT NULL,
    [is_active]     bit          NOT NULL CONSTRAINT [DF_role_permission_is_active]  DEFAULT (1),
    [is_deleted]    bit          NOT NULL CONSTRAINT [DF_role_permission_is_deleted] DEFAULT (0),
    [row_version]   rowversion   NOT NULL,
    [created_at]    datetime2(3) NOT NULL CONSTRAINT [DF_role_permission_created_at] DEFAULT (sysutcdatetime()),
    [updated_at]    datetime2(3) NOT NULL CONSTRAINT [DF_role_permission_updated_at] DEFAULT (sysutcdatetime()),
    [created_by]    varchar(26)  NULL,
    [updated_by]    varchar(26)  NULL,
    [deleted_at]    datetime2(3) NULL,
    [deleted_by]    varchar(26)  NULL,
    CONSTRAINT [PK_role_permission] PRIMARY KEY CLUSTERED ([id]),
    CONSTRAINT [CK_role_permission_user_scope] CHECK ([user_scope] IN ('system','tenant','tenant_account')),
    CONSTRAINT [CK_role_permission_deleted]    CHECK ([is_deleted] = 0 OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL)),
    CONSTRAINT [FK_role_permission_role_id]       FOREIGN KEY ([role_id], [user_scope])
        REFERENCES [auth].[role]([id], [user_scope]),
    CONSTRAINT [FK_role_permission_permission_id] FOREIGN KEY ([permission_id], [user_scope])
        REFERENCES [auth].[permission]([id], [user_scope]),
    CONSTRAINT [FK_role_permission_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_role_permission_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_role_permission_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user]([id])
);
GO

CREATE UNIQUE INDEX [UQ_role_permission]
    ON [auth].[role_permission]([role_id], [permission_id])
    INCLUDE ([is_active]) WHERE [is_deleted] = 0;
CREATE INDEX [IX_role_permission_permission_id]
    ON [auth].[role_permission]([permission_id]) WHERE [is_deleted] = 0;
GO


/* =========================================================================
   4. user_role: which roles a user holds, and where.

      user_scope       tenant_id   account_id   membership checked in
      ---------------  ----------  -----------  ---------------------------
      system           NULL        NULL         (none)
      tenant           set         NULL         auth.tenant_user
      tenant_account   set         set          auth.tenant_account_user

      user_scope + composite FKs: the user's scope, the role's scope and the
      assignment's scope must all be the same.
   ========================================================================= */
CREATE TABLE [auth].[user_role](
    [id]          varchar(26)  NOT NULL,
    [tenant_id]   varchar(26)  NULL,
    [user_id]     varchar(26)  NOT NULL,
    [account_id]  varchar(26)  NULL,
    [role_id]     varchar(26)  NOT NULL,
    [user_scope]  varchar(20)  NOT NULL,
    [is_active]   bit          NOT NULL CONSTRAINT [DF_user_role_is_active]  DEFAULT (1),
    [is_deleted]  bit          NOT NULL CONSTRAINT [DF_user_role_is_deleted] DEFAULT (0),
    [row_version] rowversion   NOT NULL,
    [created_at]  datetime2(3) NOT NULL CONSTRAINT [DF_user_role_created_at] DEFAULT (sysutcdatetime()),
    [updated_at]  datetime2(3) NOT NULL CONSTRAINT [DF_user_role_updated_at] DEFAULT (sysutcdatetime()),
    [created_by]  varchar(26)  NULL,
    [updated_by]  varchar(26)  NULL,
    [deleted_at]  datetime2(3) NULL,
    [deleted_by]  varchar(26)  NULL,
    CONSTRAINT [PK_user_role] PRIMARY KEY CLUSTERED ([id]),
    CONSTRAINT [CK_user_role_user_scope] CHECK ([user_scope] IN ('system','tenant','tenant_account')),
    -- the tenant/account columns must match the scope (table above)
    CONSTRAINT [CK_user_role_scope_shape] CHECK (
           ([user_scope] = 'system'         AND [tenant_id] IS NULL     AND [account_id] IS NULL)
        OR ([user_scope] = 'tenant'         AND [tenant_id] IS NOT NULL AND [account_id] IS NULL)
        OR ([user_scope] = 'tenant_account' AND [tenant_id] IS NOT NULL AND [account_id] IS NOT NULL)
    ),
    CONSTRAINT [CK_user_role_deleted] CHECK ([is_deleted] = 0 OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL)),
    CONSTRAINT [FK_user_role_tenant_id]  FOREIGN KEY ([tenant_id])  REFERENCES [tenant].[tenant]([id]),
    CONSTRAINT [FK_user_role_account_id] FOREIGN KEY ([account_id]) REFERENCES [tenant].[tenant_account]([id]),
    CONSTRAINT [FK_user_role_user_id]    FOREIGN KEY ([user_id], [user_scope])
        REFERENCES [auth].[app_user]([id], [user_scope]),
    CONSTRAINT [FK_user_role_role_id]    FOREIGN KEY ([role_id], [user_scope])
        REFERENCES [auth].[role]([id], [user_scope]),
    CONSTRAINT [FK_user_role_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_user_role_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_user_role_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user]([id])
);
GO

-- Uniqueness + login lookup + "list a tenant's assignments" (leads with tenant_id).
CREATE UNIQUE INDEX [UQ_user_role]
    ON [auth].[user_role]([tenant_id], [user_id], [account_id], [role_id])
    INCLUDE ([is_active]) WHERE [is_deleted] = 0;
-- "Who holds this role?" and the FK check when a role is removed.
CREATE INDEX [IX_user_role_role_id]
    ON [auth].[user_role]([role_id]) INCLUDE ([tenant_id], [user_id]) WHERE [is_deleted] = 0;
GO


/* =========================================================================
   5. role_report: report access per role, owned by a tenant.
      Platform defaults are copied in from default_role_report at onboarding,
      so every row belongs to a real tenant and the tenant can change it.
   ========================================================================= */
CREATE TABLE [auth].[role_report](
    [id]          varchar(26)  NOT NULL,
    [tenant_id]   varchar(26)  NOT NULL,
    [role_id]     varchar(26)  NOT NULL,
    [report_id]   varchar(26)  NOT NULL,
    [can_view]    bit          NOT NULL CONSTRAINT [DF_role_report_can_view]   DEFAULT (1),
    [can_export]  bit          NOT NULL CONSTRAINT [DF_role_report_can_export] DEFAULT (0),
    [is_active]   bit          NOT NULL CONSTRAINT [DF_role_report_is_active]  DEFAULT (1),
    [is_deleted]  bit          NOT NULL CONSTRAINT [DF_role_report_is_deleted] DEFAULT (0),
    [row_version] rowversion   NOT NULL,
    [created_at]  datetime2(3) NOT NULL CONSTRAINT [DF_role_report_created_at] DEFAULT (sysutcdatetime()),
    [updated_at]  datetime2(3) NOT NULL CONSTRAINT [DF_role_report_updated_at] DEFAULT (sysutcdatetime()),
    [created_by]  varchar(26)  NULL,
    [updated_by]  varchar(26)  NULL,
    [deleted_at]  datetime2(3) NULL,
    [deleted_by]  varchar(26)  NULL,
    CONSTRAINT [PK_role_report] PRIMARY KEY CLUSTERED ([id]),
    CONSTRAINT [CK_role_report_export_needs_view] CHECK ([can_export] = 0 OR [can_view] = 1),
    CONSTRAINT [CK_role_report_deleted] CHECK ([is_deleted] = 0 OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL)),
    CONSTRAINT [FK_role_report_tenant_id]  FOREIGN KEY ([tenant_id])  REFERENCES [tenant].[tenant]([id]),
    CONSTRAINT [FK_role_report_role_id]    FOREIGN KEY ([role_id])    REFERENCES [auth].[role]([id]),
    CONSTRAINT [FK_role_report_report_id]  FOREIGN KEY ([report_id])  REFERENCES [rpt].[report_definition]([id]),
    CONSTRAINT [FK_role_report_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_role_report_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_role_report_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user]([id])
);
GO

CREATE UNIQUE INDEX [UQ_role_report]
    ON [auth].[role_report]([tenant_id], [role_id], [report_id])
    INCLUDE ([can_view], [can_export], [is_active]) WHERE [is_deleted] = 0;
CREATE INDEX [IX_role_report_report_id]
    ON [auth].[role_report]([report_id]) INCLUDE ([tenant_id], [role_id]) WHERE [is_deleted] = 0;
GO


/* =========================================================================
   6. default_role_report: platform default report grants.
      Not read at runtime. Tenant onboarding copies these rows into
      role_report with the new tenant_id; an explicit "apply to all
      tenants" script inserts only missing rows when a default is added later.
      role_id must be a platform template role (tenant_id NULL) - service rule.
      report_id must be a platform-wide report definition - service rule.
   ========================================================================= */
CREATE TABLE [auth].[default_role_report](
    [id]          varchar(26)  NOT NULL,
    [role_id]     varchar(26)  NOT NULL,
    [report_id]   varchar(26)  NOT NULL,
    [can_view]    bit          NOT NULL CONSTRAINT [DF_default_role_report_can_view]   DEFAULT (1),
    [can_export]  bit          NOT NULL CONSTRAINT [DF_default_role_report_can_export] DEFAULT (0),
    [is_active]   bit          NOT NULL CONSTRAINT [DF_default_role_report_is_active]  DEFAULT (1),
    [is_deleted]  bit          NOT NULL CONSTRAINT [DF_default_role_report_is_deleted] DEFAULT (0),
    [row_version] rowversion   NOT NULL,
    [created_at]  datetime2(3) NOT NULL CONSTRAINT [DF_default_role_report_created_at] DEFAULT (sysutcdatetime()),
    [updated_at]  datetime2(3) NOT NULL CONSTRAINT [DF_default_role_report_updated_at] DEFAULT (sysutcdatetime()),
    [created_by]  varchar(26)  NULL,
    [updated_by]  varchar(26)  NULL,
    [deleted_at]  datetime2(3) NULL,
    [deleted_by]  varchar(26)  NULL,
    CONSTRAINT [PK_default_role_report] PRIMARY KEY CLUSTERED ([id]),
    CONSTRAINT [CK_default_role_report_export_needs_view] CHECK ([can_export] = 0 OR [can_view] = 1),
    CONSTRAINT [CK_default_role_report_deleted] CHECK ([is_deleted] = 0 OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL)),
    CONSTRAINT [FK_default_role_report_role_id]    FOREIGN KEY ([role_id])    REFERENCES [auth].[role]([id]),
    CONSTRAINT [FK_default_role_report_report_id]  FOREIGN KEY ([report_id])  REFERENCES [rpt].[report_definition]([id]),
    CONSTRAINT [FK_default_role_report_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_default_role_report_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_default_role_report_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user]([id])
);
GO

CREATE UNIQUE INDEX [UQ_default_role_report]
    ON [auth].[default_role_report]([role_id], [report_id]) WHERE [is_deleted] = 0;
GO


/* =========================================================================
   7. Retire the old per-user grant tables.
   ========================================================================= */
IF OBJECT_ID('rpt.report_permission', 'U') IS NOT NULL
    DROP TABLE [rpt].[report_permission];
GO

-- txn.screen_permission is replaced by auth.permission (resource_type = 'screen').
-- Before dropping: check it holds no data worth migrating, and that nothing
-- references it (sys.sql_expression_dependencies + application code). Then uncomment:
-- IF OBJECT_ID('txn.screen_permission', 'U') IS NOT NULL
--     DROP TABLE [txn].[screen_permission];
-- GO


/* =========================================================================
   8. Runtime grants — mutable catalogs (not append-only).
      If deevo_ddl lacks permission to GRANT, run this block as dbo.
   ========================================================================= */
IF DATABASE_PRINCIPAL_ID('deevo_app') IS NOT NULL
BEGIN
    GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[auth].[permission] TO [deevo_app];
    GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[auth].[role] TO [deevo_app];
    GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[auth].[role_permission] TO [deevo_app];
    GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[auth].[user_role] TO [deevo_app];
    GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[auth].[role_report] TO [deevo_app];
    GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[auth].[default_role_report] TO [deevo_app];
END;
GO
