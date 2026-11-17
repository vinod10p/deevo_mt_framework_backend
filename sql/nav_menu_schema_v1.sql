/*
nav_menu_schema_v1.sql
Dynamic menu tables (v1): nav.menu_module, nav.menu_item.

Apply in SSMS as deevo_ddl on deevo_app_dev2. If GRANT fails, run the GRANT
block as dbo. Runtime user deevo_app is SELECT/INSERT/UPDATE/DELETE (mutable
catalog, not append-only audit).

Needs auth.app_user and rpt.report_definition.
Replaces the earlier draft create_nav_menu.sql.
*/

USE [deevo_app_dev2]
GO

SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO

/* =========================================================================
   Dynamic submenu  (v1)

   Scope of v1:
     - Main modules AND submenus come from the database; React renders
       whatever GET /api/v1/nav/menu returns.
       Module codes carry no scope prefix (CRM, WF, EMAIL); user_scope says
       whether a module is for tenant staff, the portal, or system staff.
     - Submenus: one or two levels, each item is a group or a report.
     - Platform-defined. Tenants can't change anything. All reports open.
     - Tenant scope only for now; portal modules are added later as new rows.

   Depth rule (enforced by the database):
     level 1: group or report   (parent_id NULL)
     level 2: report only       (parent is a group in the same module)

   Replaces the earlier draft create_nav_menu.sql.
   ========================================================================= */

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'nav')
    EXEC('CREATE SCHEMA [nav] AUTHORIZATION [dbo]');
GO


/* =========================================================================
   1. menu_module: one row per main menu entry.
      React renders name and icon from the API; user_scope decides who can
      ever receive the module.

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
    [name]        nvarchar(100) NOT NULL,           -- label shown in the main menu, e.g. 'CRM'
    [icon]        varchar(50)   NULL,               -- icon name React maps to a component; default icon if unknown
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
    CONSTRAINT [CK_menu_module_user_scope] CHECK ([user_scope] IN ('system','tenant','tenant_account')),
    -- codes are uppercase (checked case-sensitively)
    CONSTRAINT [CK_menu_module_code_upper] CHECK ([code] = UPPER([code]) COLLATE Latin1_General_CS_AS),
    CONSTRAINT [CK_menu_module_deleted]    CHECK ([is_deleted] = 0 OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL)),
    CONSTRAINT [FK_menu_module_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_menu_module_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_menu_module_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user]([id])
);
GO

-- Code unique within a scope; the same code may exist for tenant and portal.
CREATE UNIQUE INDEX [UQ_menu_module_scope_code]
    ON [nav].[menu_module]([user_scope], [code]) WHERE [is_deleted] = 0;

-- Loading one scope's modules in display order.
CREATE INDEX [IX_menu_module_scope]
    ON [nav].[menu_module]([user_scope], [sort_order])
    INCLUDE ([code], [name], [icon], [is_active]) WHERE [is_deleted] = 0;
GO


/* =========================================================================
   2. menu_item: submenu entries under a module.

      item_type   parent_id                 report_id
      ---------   -----------------------   ---------
      group       NULL (level 1 only)       NULL
      report      NULL or a group's id      required

      parent_item_type is a persisted computed column ('group' when parent_id
      is set, NULL otherwise) so the composite FK can guarantee the parent is
      a group in the same module without callers having to set it manually.
   ========================================================================= */
CREATE TABLE [nav].[menu_item](
    [id]               varchar(26)   NOT NULL,
    [module_id]        varchar(26)   NOT NULL,
    [parent_id]        varchar(26)   NULL,
    [code]             varchar(100)  NOT NULL,      -- module code + item, e.g. 'CRM.LEADS'
    [item_type]        varchar(10)   NOT NULL,      -- group | report
    [label]            nvarchar(100) NOT NULL,
    [icon]             varchar(50)   NULL,
    [report_id]        varchar(26)   NULL,
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
    -- target for the parent FK: (id, module, type)
    CONSTRAINT [UQ_menu_item_id_module_type] UNIQUE ([id], [module_id], [item_type]),
    CONSTRAINT [CK_menu_item_item_type]  CHECK ([item_type] IN ('group','report')),
    -- codes are uppercase (checked case-sensitively, matching menu_module.code)
    CONSTRAINT [CK_menu_item_code_upper] CHECK ([code] = UPPER([code]) COLLATE Latin1_General_CS_AS),
    -- groups have no report and live at level 1; reports always point to a report
    CONSTRAINT [CK_menu_item_shape] CHECK (
           ([item_type] = 'group'  AND [report_id] IS NULL     AND [parent_id] IS NULL)
        OR ([item_type] = 'report' AND [report_id] IS NOT NULL)
    ),
    CONSTRAINT [CK_menu_item_deleted] CHECK ([is_deleted] = 0 OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL)),
    CONSTRAINT [FK_menu_item_module_id] FOREIGN KEY ([module_id]) REFERENCES [nav].[menu_module]([id]),
    -- parent must be a group in the same module
    CONSTRAINT [FK_menu_item_parent_id] FOREIGN KEY ([parent_id], [module_id], [parent_item_type])
        REFERENCES [nav].[menu_item]([id], [module_id], [item_type]),
    CONSTRAINT [FK_menu_item_report_id]  FOREIGN KEY ([report_id])  REFERENCES [rpt].[report_definition]([id]),
    CONSTRAINT [FK_menu_item_created_by] FOREIGN KEY ([created_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_menu_item_updated_by] FOREIGN KEY ([updated_by]) REFERENCES [auth].[app_user]([id]),
    CONSTRAINT [FK_menu_item_deleted_by] FOREIGN KEY ([deleted_by]) REFERENCES [auth].[app_user]([id])
);
GO

-- Code unique within a module; tenant and portal modules may both have 'CRM.LEADS'.
CREATE UNIQUE INDEX [UQ_menu_item_module_code]
    ON [nav].[menu_item]([module_id], [code]) WHERE [is_deleted] = 0;

-- Loading a module's tree in display order.
CREATE INDEX [IX_menu_item_module_tree]
    ON [nav].[menu_item]([module_id], [parent_id], [sort_order])
    INCLUDE ([code], [item_type], [label], [icon], [report_id], [is_active])
    WHERE [is_deleted] = 0;

-- FK check when a report definition is removed; "which menus show this report?"
CREATE INDEX [IX_menu_item_report_id]
    ON [nav].[menu_item]([report_id])
    INCLUDE ([is_deleted])
    WHERE [report_id] IS NOT NULL;
GO


/* =========================================================================
   3. Application permissions for deevo_app
      If deevo_ddl lacks permission to run GRANT, run this block as dbo.
   ========================================================================= */
IF DATABASE_PRINCIPAL_ID('deevo_app') IS NOT NULL
BEGIN
    GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[nav].[menu_module] TO [deevo_app];
    GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::[nav].[menu_item]   TO [deevo_app];
END;
GO
