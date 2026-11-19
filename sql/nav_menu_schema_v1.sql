/*
nav_menu_schema_v1.sql
Dynamic menu tables: nav.menu_module, nav.screen, nav.menu_item.

DEV RECREATE: drops existing nav tables (loses seed), then creates this
structure. Apply in SSMS as deevo_ddl on deevo_app_dev2, then run
nav_menu_seed_v1.sql. If GRANT fails, run the GRANT block as dbo.

Runtime user deevo_app is SELECT/INSERT/UPDATE/DELETE (mutable catalog).

Needs auth.app_user and rpt.report_definition.
nav.screen is a SPA-route catalog (not txn.screen). Do not reuse
txn.screen.screen_key values (e.g. 'lead') as nav.screen.code.
*/

USE [deevo_app_dev2]
GO

SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'nav')
    EXEC('CREATE SCHEMA [nav] AUTHORIZATION [dbo]');
GO

/* Dev-only: wipe current nav catalog so CREATE can run. */
IF OBJECT_ID(N'nav.menu_item', N'U') IS NOT NULL
    DROP TABLE [nav].[menu_item];
IF OBJECT_ID(N'nav.screen', N'U') IS NOT NULL
    DROP TABLE [nav].[screen];
IF OBJECT_ID(N'nav.menu_module', N'U') IS NOT NULL
    DROP TABLE [nav].[menu_module];
GO


/* =========================================================================
   Dynamic menu  (v1)

   Scope of v1:
     - Main modules AND submenus come from the database; React renders
       GET /api/nav/modules and GET /api/nav/modules/{code}/items
       (DeevoFlow remounts the same handlers at /api/v1/nav/...).
       Module codes carry no scope prefix (CRM, WF, EMAIL); user_scope says
       whether a module is for tenant staff, the portal, or system staff.
     - A menu item is a group, a report, or a screen.
     - Platform-defined. Tenants can't change anything. All reports open.
     - Tenant scope only for now; portal modules are added later as new rows.

   Tables:
     nav.menu_module  - main menu entries (CRM, WF, EMAIL), one set per user_scope
     nav.screen       - catalog of non-report SPA routes a menu can open
     nav.menu_item    - submenu entries: group | report | screen

   Depth rule (enforced by the database):
     level 1: group, report or screen   (parent_id NULL)
     level 2: report or screen          (parent is a group in the same module)

   Scope rule (enforced by the database):
     an item's user_scope equals its module's, and a screen item's screen
     has that same user_scope. A tenant module can't open a portal screen.
   ========================================================================= */


/* =========================================================================
   1. menu_module: one row per main menu entry.

      user_scope uses the same values as auth.app_user.user_scope, so the API
      compares it directly with the scope in the user's token:
        tenant          = tenant staff
        tenant_account  = portal (tenant's customers)
        system          = platform staff
      The same code can exist once per scope: tenant 'CRM' and portal 'CRM'
      are different modules with different submenus.
   ========================================================================= */
CREATE TABLE [nav].[menu_module](
    [id]          varchar(26)   NOT NULL,
    [code]        varchar(50)   NOT NULL,           -- 'CRM', 'WF', 'EMAIL'
    [name]        nvarchar(100) NOT NULL,           -- label shown in the main menu
    [icon]        varchar(50)   NULL,               -- icon name React maps to a component
    [user_scope]  varchar(20)   NOT NULL,           -- tenant | tenant_account (portal) | system
    [sort_order]  int           NOT NULL CONSTRAINT [DF_menu_module_sort_order] DEFAULT (0),
    [is_active]   bit           NOT NULL CONSTRAINT [DF_menu_module_is_active]  DEFAULT (1),
    [is_deleted]  bit           NOT NULL CONSTRAINT [DF_menu_module_is_deleted] DEFAULT (0),
    [row_version] rowversion    NOT NULL,
    [created_at]  datetime2(3)  NOT NULL CONSTRAINT [DF_menu_module_created_at] DEFAULT (sysutcdatetime()),
    [updated_at]  datetime2(3)  NOT NULL CONSTRAINT [DF_menu_module_updated_at] DEFAULT (sysutcdatetime()),
    [created_by]  varchar(26)   NULL,
    [updated_by]  varchar(26)   NULL,
    [deleted_at]  datetime2(3)  NULL,
    [deleted_by]  varchar(26)   NULL,
    CONSTRAINT [PK_menu_module] PRIMARY KEY CLUSTERED ([id]),
    CONSTRAINT [UQ_menu_module_id_user_scope] UNIQUE ([id], [user_scope]),
    CONSTRAINT [CK_menu_module_user_scope] CHECK ([user_scope] IN ('system','tenant','tenant_account')),
    CONSTRAINT [CK_menu_module_code_upper] CHECK ([code] = UPPER([code]) COLLATE Latin1_General_CS_AS),
    CONSTRAINT [CK_menu_module_deleted]    CHECK ([is_deleted] = 0 OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL)),
    CONSTRAINT [FK_menu_module_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_menu_module_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_menu_module_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user]([id])
);
GO

CREATE UNIQUE INDEX [UQ_menu_module_scope_code]
    ON [nav].[menu_module]([user_scope], [code]) WHERE [is_deleted] = 0;

CREATE INDEX [IX_menu_module_scope]
    ON [nav].[menu_module]([user_scope], [sort_order])
    INCLUDE ([code], [name], [icon], [is_active]) WHERE [is_deleted] = 0;
GO


/* =========================================================================
   2. screen: catalog of SPA routes that are not reports
      (dashboards, settings, email compose, workflow designer, ...).

      Not txn.screen (Lead form metadata). nav.screen.code must not equal
      a live txn.screen.screen_key (e.g. do not use 'lead').

      The database holds a stable code; React maps the code to its route.
      Later, screen permissions may use the same code:
        auth.permission.resource_code = screen.code, e.g. 'screen.crm_dashboard.view'
   ========================================================================= */
CREATE TABLE [nav].[screen](
    [id]          varchar(26)   NOT NULL,
    [code]        varchar(100)  NOT NULL,           -- 'crm_dashboard', 'email_compose'
    [name]        nvarchar(100) NOT NULL,
    [description] nvarchar(300) NULL,
    [user_scope]  varchar(20)   NOT NULL,           -- who the screen is built for
    [is_active]   bit           NOT NULL CONSTRAINT [DF_nav_screen_is_active]  DEFAULT (1),
    [is_deleted]  bit           NOT NULL CONSTRAINT [DF_nav_screen_is_deleted] DEFAULT (0),
    [row_version] rowversion    NOT NULL,
    [created_at]  datetime2(3)  NOT NULL CONSTRAINT [DF_nav_screen_created_at] DEFAULT (sysutcdatetime()),
    [updated_at]  datetime2(3)  NOT NULL CONSTRAINT [DF_nav_screen_updated_at] DEFAULT (sysutcdatetime()),
    [created_by]  varchar(26)   NULL,
    [updated_by]  varchar(26)   NULL,
    [deleted_at]  datetime2(3)  NULL,
    [deleted_by]  varchar(26)   NULL,
    CONSTRAINT [PK_nav_screen] PRIMARY KEY CLUSTERED ([id]),
    CONSTRAINT [UQ_nav_screen_id_user_scope] UNIQUE ([id], [user_scope]),
    CONSTRAINT [CK_nav_screen_user_scope] CHECK ([user_scope] IN ('system','tenant','tenant_account')),
    CONSTRAINT [CK_nav_screen_code_lower] CHECK ([code] = LOWER([code]) COLLATE Latin1_General_CS_AS),
    CONSTRAINT [CK_nav_screen_deleted]    CHECK ([is_deleted] = 0 OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL)),
    CONSTRAINT [FK_nav_screen_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_nav_screen_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_nav_screen_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user]([id])
);
GO

CREATE UNIQUE INDEX [UQ_nav_screen_code]
    ON [nav].[screen]([code]) WHERE [is_deleted] = 0;
GO


/* =========================================================================
   3. menu_item: entries under a module.

      item_type   parent_id                 report_id   screen_id
      ---------   -----------------------   ---------   ---------
      group       NULL (level 1 only)       NULL        NULL
      report      NULL or a group's id      required    NULL
      screen      NULL or a group's id      NULL        required

      user_scope is copied from the module (composite FK guarantees it) so
      that screen items can be checked against the screen's scope.

      parent_item_type is persisted computed ('group' when parent_id is set)
      so the composite FK can require the parent to be a group in the same
      module without callers setting it.
   ========================================================================= */
CREATE TABLE [nav].[menu_item](
    [id]               varchar(26)   NOT NULL,
    [module_id]        varchar(26)   NOT NULL,
    [user_scope]       varchar(20)   NOT NULL,
    [parent_id]        varchar(26)   NULL,
    [code]             varchar(100)  NOT NULL,      -- module code + item, e.g. 'CRM.LEADS'
    [item_type]        varchar(10)   NOT NULL,      -- group | report | screen
    [label]            nvarchar(100) NOT NULL,
    [icon]             varchar(50)   NULL,
    [report_id]        varchar(26)   NULL,
    [screen_id]        varchar(26)   NULL,
    [sort_order]       int           NOT NULL CONSTRAINT [DF_menu_item_sort_order] DEFAULT (0),
    [is_active]        bit           NOT NULL CONSTRAINT [DF_menu_item_is_active]  DEFAULT (1),
    [is_deleted]       bit           NOT NULL CONSTRAINT [DF_menu_item_is_deleted] DEFAULT (0),
    [row_version]      rowversion    NOT NULL,
    [created_at]       datetime2(3)  NOT NULL CONSTRAINT [DF_menu_item_created_at] DEFAULT (sysutcdatetime()),
    [updated_at]       datetime2(3)  NOT NULL CONSTRAINT [DF_menu_item_updated_at] DEFAULT (sysutcdatetime()),
    [created_by]       varchar(26)   NULL,
    [updated_by]       varchar(26)   NULL,
    [deleted_at]       datetime2(3)  NULL,
    [deleted_by]       varchar(26)   NULL,
    [parent_item_type] AS (CASE WHEN [parent_id] IS NOT NULL THEN CONVERT(varchar(10), 'group') END) PERSISTED,
    CONSTRAINT [PK_menu_item] PRIMARY KEY CLUSTERED ([id]),
    CONSTRAINT [UQ_menu_item_id_module_type] UNIQUE ([id], [module_id], [item_type]),
    CONSTRAINT [CK_menu_item_item_type]  CHECK ([item_type] IN ('group','report','screen')),
    CONSTRAINT [CK_menu_item_user_scope] CHECK ([user_scope] IN ('system','tenant','tenant_account')),
    CONSTRAINT [CK_menu_item_code_upper] CHECK ([code] = UPPER([code]) COLLATE Latin1_General_CS_AS),
    CONSTRAINT [CK_menu_item_shape] CHECK (
           ([item_type] = 'group'  AND [report_id] IS NULL     AND [screen_id] IS NULL     AND [parent_id] IS NULL)
        OR ([item_type] = 'report' AND [report_id] IS NOT NULL AND [screen_id] IS NULL)
        OR ([item_type] = 'screen' AND [screen_id] IS NOT NULL AND [report_id] IS NULL)
    ),
    CONSTRAINT [CK_menu_item_deleted] CHECK ([is_deleted] = 0 OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL)),
    CONSTRAINT [FK_menu_item_module_id] FOREIGN KEY ([module_id], [user_scope])
        REFERENCES [nav].[menu_module]([id], [user_scope]),
    CONSTRAINT [FK_menu_item_parent_id] FOREIGN KEY ([parent_id], [module_id], [parent_item_type])
        REFERENCES [nav].[menu_item]([id], [module_id], [item_type]),
    CONSTRAINT [FK_menu_item_report_id] FOREIGN KEY ([report_id]) REFERENCES [rpt].[report_definition]([id]),
    CONSTRAINT [FK_menu_item_screen_id] FOREIGN KEY ([screen_id], [user_scope])
        REFERENCES [nav].[screen]([id], [user_scope]),
    CONSTRAINT [FK_menu_item_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_menu_item_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_menu_item_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user]([id])
);
GO

CREATE UNIQUE INDEX [UQ_menu_item_module_code]
    ON [nav].[menu_item]([module_id], [code]) WHERE [is_deleted] = 0;

CREATE INDEX [IX_menu_item_module_tree]
    ON [nav].[menu_item]([module_id], [parent_id], [sort_order])
    INCLUDE ([code], [item_type], [label], [icon], [report_id], [screen_id], [is_active])
    WHERE [is_deleted] = 0;

CREATE INDEX [IX_menu_item_report_id]
    ON [nav].[menu_item]([report_id])
    INCLUDE ([is_deleted])
    WHERE [report_id] IS NOT NULL;

CREATE INDEX [IX_menu_item_screen_id]
    ON [nav].[menu_item]([screen_id])
    INCLUDE ([is_deleted])
    WHERE [screen_id] IS NOT NULL;
GO


/* =========================================================================
   4. Application permissions for deevo_app
      If deevo_ddl lacks permission to run GRANT, run this block as dbo.
   ========================================================================= */
IF DATABASE_PRINCIPAL_ID('deevo_app') IS NOT NULL
BEGIN
    GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[nav].[menu_module] TO [deevo_app];
    GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[nav].[screen]      TO [deevo_app];
    GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[nav].[menu_item]   TO [deevo_app];
END;
GO
