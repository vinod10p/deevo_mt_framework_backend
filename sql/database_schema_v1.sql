USE [deevo_app_dev2]
GO
/****** Object:  Table [audit].[audit_log]    Script Date: 5/18/2026 6:33:24 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [audit].[audit_log](
	[id] [varchar](26) NOT NULL,
	[tenant_id] [varchar](26) NULL,
	[session_id] [varchar](26) NULL,
	[user_id] [varchar](26) NULL,
	[user_type] [varchar](20) NULL,
	[schema_name] [varchar](50) NOT NULL,
	[table_name] [varchar](100) NOT NULL,
	[record_id] [varchar](26) NOT NULL,
	[action] [varchar](20) NOT NULL,
	[old_values] [nvarchar](max) NULL,
	[new_values] [nvarchar](max) NULL,
	[ip_address] [varchar](45) NULL,
	[user_agent] [nvarchar](500) NULL,
	[reason] [nvarchar](500) NULL,
	[created_at] [datetime2](3) NOT NULL,
 CONSTRAINT [PK_audit_log] PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
/****** Object:  Table [auth].[app_user]    Script Date: 5/18/2026 6:33:24 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [auth].[app_user](
	[id] [varchar](26) NOT NULL,
	[email] [varchar](255) NOT NULL,
	[first_name] [varchar](100) NULL,
	[last_name] [varchar](100) NULL,
	[phone] [varchar](20) NULL,
	[avatar_url] [varchar](500) NULL,
	[password_hash] [varchar](500) NULL,
	[password_changed_at] [datetime2](3) NULL,
	[auth_provider] [varchar](30) NOT NULL,
	[external_id] [varchar](255) NULL,
	[email_verified_at] [datetime2](3) NULL,
	[last_login_at] [datetime2](3) NULL,
	[is_active] [bit] NOT NULL,
	[is_deleted] [bit] NOT NULL,
	[failed_login_count] [int] NOT NULL,
	[locked_until] [datetime2](3) NULL,
	[mfa_enabled] [bit] NOT NULL,
	[mfa_secret_enc] [varchar](512) NULL,
	[mfa_confirmed_at] [datetime2](3) NULL,
	[row_version] [timestamp] NOT NULL,
	[created_at] [datetime2](3) NOT NULL,
	[updated_at] [datetime2](3) NOT NULL,
	[created_by] [varchar](26) NULL,
	[updated_by] [varchar](26) NULL,
	[email_normalized]  AS (lower(ltrim(rtrim([email])))) PERSISTED,
	[user_scope] [varchar](20) NOT NULL,
	[deleted_by] [varchar](26) NULL,
 CONSTRAINT [PK_app_user] PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [auth].[session]    Script Date: 5/18/2026 6:33:24 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [auth].[session](
	[id] [varchar](26) NOT NULL,
	[user_id] [varchar](26) NOT NULL,
	[user_type] [varchar](20) NOT NULL,
	[tenant_id] [varchar](26) NULL,
	[token_hash] [binary](32) NOT NULL,
	[refresh_token_hash] [binary](32) NULL,
	[auth_method] [varchar](20) NOT NULL,
	[created_from] [varchar](20) NOT NULL,
	[expires_at] [datetime2](3) NOT NULL,
	[refresh_expires_at] [datetime2](3) NULL,
	[last_activity] [datetime2](3) NOT NULL,
	[is_active] [bit] NOT NULL,
	[is_deleted] [bit] NOT NULL,
	[revoked_at] [datetime2](3) NULL,
	[revoke_reason] [nvarchar](200) NULL,
	[revoked_by] [varchar](26) NULL,
	[ip_address] [varchar](45) NULL,
	[user_agent] [nvarchar](500) NULL,
	[device_info] [nvarchar](200) NULL,
	[row_version] [timestamp] NOT NULL,
	[created_at] [datetime2](3) NOT NULL,
	[updated_at] [datetime2](3) NOT NULL,
	[deleted_by] [varchar](26) NULL,
 CONSTRAINT [PK_session] PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [auth].[tenant_account_user]    Script Date: 5/18/2026 6:33:24 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [auth].[tenant_account_user](
	[id] [varchar](26) NOT NULL,
	[tenant_id] [varchar](26) NOT NULL,
	[account_id] [varchar](26) NOT NULL,
	[user_id] [varchar](26) NOT NULL,
	[role] [varchar](20) NOT NULL,
	[invited_at] [datetime2](3) NULL,
	[invited_by] [varchar](26) NULL,
	[invite_token_hash] [binary](32) NULL,
	[joined_at] [datetime2](3) NULL,
	[is_active] [bit] NOT NULL,
	[is_deleted] [bit] NOT NULL,
	[row_version] [timestamp] NOT NULL,
	[created_at] [datetime2](3) NOT NULL,
	[updated_at] [datetime2](3) NOT NULL,
	[created_by] [varchar](26) NULL,
	[updated_by] [varchar](26) NULL,
	[deleted_by] [varchar](26) NULL,
 CONSTRAINT [PK_tenant_account_user] PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_tenant_account_user] UNIQUE NONCLUSTERED 
(
	[tenant_id] ASC,
	[account_id] ASC,
	[user_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [auth].[tenant_user]    Script Date: 5/18/2026 6:33:24 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [auth].[tenant_user](
	[id] [varchar](26) NOT NULL,
	[tenant_id] [varchar](26) NOT NULL,
	[user_id] [varchar](26) NOT NULL,
	[role] [varchar](20) NOT NULL,
	[invited_at] [datetime2](3) NULL,
	[invited_by] [varchar](26) NULL,
	[invite_token_hash] [binary](32) NULL,
	[joined_at] [datetime2](3) NULL,
	[is_active] [bit] NOT NULL,
	[is_deleted] [bit] NOT NULL,
	[row_version] [timestamp] NOT NULL,
	[created_at] [datetime2](3) NOT NULL,
	[updated_at] [datetime2](3) NOT NULL,
	[created_by] [varchar](26) NULL,
	[updated_by] [varchar](26) NULL,
	[deleted_by] [varchar](26) NULL,
	[invite_token] [varchar](255) NULL,
 CONSTRAINT [PK_tenant_user] PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_tenant_user] UNIQUE NONCLUSTERED 
(
	[tenant_id] ASC,
	[user_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [tenant].[tenant]    Script Date: 5/18/2026 6:33:24 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [tenant].[tenant](
	[id] [varchar](26) NOT NULL,
	[name] [nvarchar](255) NOT NULL,
	[subdomain] [varchar](100) NOT NULL,
	[status] [varchar](20) NOT NULL,
	[is_active] [bit] NOT NULL,
	[is_deleted] [bit] NOT NULL,
	[plan_type] [varchar](50) NOT NULL,
	[max_users] [int] NOT NULL,
	[max_agents] [int] NOT NULL,
	[max_contacts] [int] NULL,
	[storage_limit_gb] [int] NULL,
	[subscription_start_date] [datetime2](3) NULL,
	[subscription_end_date] [datetime2](3) NULL,
	[billing_email] [varchar](255) NULL,
	[contact_email] [varchar](255) NULL,
	[contact_phone] [varchar](50) NULL,
	[address_line1] [nvarchar](255) NULL,
	[address_line2] [nvarchar](255) NULL,
	[city] [nvarchar](100) NULL,
	[state] [nvarchar](100) NULL,
	[postal_code] [varchar](20) NULL,
	[country] [varchar](2) NULL,
	[timezone] [varchar](50) NOT NULL,
	[locale] [varchar](10) NOT NULL,
	[logo_url] [varchar](500) NULL,
	[settings] [nvarchar](max) NULL,
	[features_enabled] [nvarchar](max) NULL,
	[row_version] [timestamp] NOT NULL,
	[created_at] [datetime2](3) NOT NULL,
	[updated_at] [datetime2](3) NOT NULL,
	[created_by] [varchar](26) NULL,
	[updated_by] [varchar](26) NULL,
	[deleted_by] [varchar](26) NULL,
 CONSTRAINT [PK_tenant] PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
/****** Object:  Table [tenant].[tenant_account]    Script Date: 5/18/2026 6:33:24 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [tenant].[tenant_account](
	[id] [varchar](26) NOT NULL,
	[tenant_id] [varchar](26) NOT NULL,
	[account_code] [varchar](26) NOT NULL,
	[account_type] [nvarchar](50) NOT NULL,
	[name] [nvarchar](255) NOT NULL,
	[email] [varchar](255) NULL,
	[phone] [varchar](50) NULL,
	[website] [varchar](500) NULL,
	[custom_fields] [nvarchar](max) NULL,
	[status] [varchar](20) NOT NULL,
	[is_active] [bit] NOT NULL,
	[is_deleted] [bit] NOT NULL,
	[row_version] [timestamp] NOT NULL,
	[created_at] [datetime2](3) NOT NULL,
	[updated_at] [datetime2](3) NOT NULL,
	[created_by] [varchar](26) NULL,
	[updated_by] [varchar](26) NULL,
	[deleted_by] [varchar](26) NULL,
 CONSTRAINT [PK_tenant_account] PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_tenant_account_code] UNIQUE NONCLUSTERED 
(
	[tenant_id] ASC,
	[account_code] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
/****** Object:  Table [tenant].[tenant_account_address]    Script Date: 5/18/2026 6:33:24 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [tenant].[tenant_account_address](
	[id] [varchar](26) NOT NULL,
	[tenant_id] [varchar](26) NOT NULL,
	[account_id] [varchar](26) NOT NULL,
	[address_type] [nvarchar](50) NOT NULL,
	[is_default] [bit] NOT NULL,
	[address_line1] [nvarchar](255) NOT NULL,
	[address_line2] [nvarchar](255) NULL,
	[city] [nvarchar](100) NULL,
	[state] [nvarchar](100) NULL,
	[postal_code] [varchar](20) NULL,
	[country] [varchar](2) NULL,
	[is_active] [bit] NOT NULL,
	[is_deleted] [bit] NOT NULL,
	[row_version] [timestamp] NOT NULL,
	[created_at] [datetime2](3) NOT NULL,
	[updated_at] [datetime2](3) NOT NULL,
	[created_by] [varchar](26) NULL,
	[updated_by] [varchar](26) NULL,
	[deleted_by] [varchar](26) NULL,
 CONSTRAINT [PK_tenant_account_address] PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [tenant].[tenant_setting]    Script Date: 5/18/2026 6:33:24 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [tenant].[tenant_setting](
	[id] [varchar](26) NOT NULL,
	[tenant_id] [varchar](26) NOT NULL,
	[key] [varchar](100) NOT NULL,
	[value] [nvarchar](max) NULL,
	[is_active] [bit] NOT NULL,
	[is_deleted] [bit] NOT NULL,
	[row_version] [timestamp] NOT NULL,
	[created_at] [datetime2](3) NOT NULL,
	[updated_at] [datetime2](3) NOT NULL,
	[created_by] [varchar](26) NULL,
	[updated_by] [varchar](26) NULL,
	[deleted_by] [varchar](26) NULL,
 CONSTRAINT [PK_tenant_setting] PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
ALTER TABLE [audit].[audit_log] ADD  CONSTRAINT [DF_audit_log_created_at]  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [auth].[app_user] ADD  CONSTRAINT [DF_app_user_auth_provider]  DEFAULT ('local') FOR [auth_provider]
GO
ALTER TABLE [auth].[app_user] ADD  CONSTRAINT [DF_app_user_is_active]  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [auth].[app_user] ADD  CONSTRAINT [DF_app_user_is_deleted]  DEFAULT ((0)) FOR [is_deleted]
GO
ALTER TABLE [auth].[app_user] ADD  CONSTRAINT [DF_app_user_failed_login_count]  DEFAULT ((0)) FOR [failed_login_count]
GO
ALTER TABLE [auth].[app_user] ADD  CONSTRAINT [DF_app_user_mfa_enabled]  DEFAULT ((0)) FOR [mfa_enabled]
GO
ALTER TABLE [auth].[app_user] ADD  CONSTRAINT [DF_app_user_created_at]  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [auth].[app_user] ADD  CONSTRAINT [DF_app_user_updated_at]  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [auth].[app_user] ADD  CONSTRAINT [DF_app_user_user_scope]  DEFAULT ('tenant') FOR [user_scope]
GO
ALTER TABLE [auth].[session] ADD  CONSTRAINT [DF_session_last_activity]  DEFAULT (sysutcdatetime()) FOR [last_activity]
GO
ALTER TABLE [auth].[session] ADD  CONSTRAINT [DF_session_is_active]  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [auth].[session] ADD  CONSTRAINT [DF_session_is_deleted]  DEFAULT ((0)) FOR [is_deleted]
GO
ALTER TABLE [auth].[session] ADD  CONSTRAINT [DF_session_created_at]  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [auth].[session] ADD  CONSTRAINT [DF_session_updated_at]  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [auth].[tenant_account_user] ADD  CONSTRAINT [DF_tenant_account_user_role]  DEFAULT ('member') FOR [role]
GO
ALTER TABLE [auth].[tenant_account_user] ADD  CONSTRAINT [DF_tenant_account_user_is_active]  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [auth].[tenant_account_user] ADD  CONSTRAINT [DF_tenant_account_user_is_deleted]  DEFAULT ((0)) FOR [is_deleted]
GO
ALTER TABLE [auth].[tenant_account_user] ADD  CONSTRAINT [DF_tenant_account_user_created_at]  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [auth].[tenant_account_user] ADD  CONSTRAINT [DF_tenant_account_user_updated_at]  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [auth].[tenant_user] ADD  CONSTRAINT [DF_tenant_user_is_active]  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [auth].[tenant_user] ADD  CONSTRAINT [DF_tenant_user_is_deleted]  DEFAULT ((0)) FOR [is_deleted]
GO
ALTER TABLE [auth].[tenant_user] ADD  CONSTRAINT [DF_tenant_user_created_at]  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [auth].[tenant_user] ADD  CONSTRAINT [DF_tenant_user_updated_at]  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_status]  DEFAULT ('trial') FOR [status]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_is_active]  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_is_deleted]  DEFAULT ((0)) FOR [is_deleted]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_plan_type]  DEFAULT ('trial') FOR [plan_type]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_max_users]  DEFAULT ((10)) FOR [max_users]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_max_agents]  DEFAULT ((5)) FOR [max_agents]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_max_contacts]  DEFAULT ((10000)) FOR [max_contacts]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_storage_limit_gb]  DEFAULT ((10)) FOR [storage_limit_gb]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_timezone]  DEFAULT ('UTC') FOR [timezone]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_locale]  DEFAULT ('en-US') FOR [locale]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_created_at]  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [tenant].[tenant] ADD  CONSTRAINT [DF_tenant_updated_at]  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [tenant].[tenant_account] ADD  CONSTRAINT [DF_tenant_account_status]  DEFAULT ('active') FOR [status]
GO
ALTER TABLE [tenant].[tenant_account] ADD  CONSTRAINT [DF_tenant_account_is_active]  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [tenant].[tenant_account] ADD  CONSTRAINT [DF_tenant_account_is_deleted]  DEFAULT ((0)) FOR [is_deleted]
GO
ALTER TABLE [tenant].[tenant_account] ADD  CONSTRAINT [DF_tenant_account_created_at]  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [tenant].[tenant_account] ADD  CONSTRAINT [DF_tenant_account_updated_at]  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [tenant].[tenant_account_address] ADD  CONSTRAINT [DF_tenant_account_address_is_default]  DEFAULT ((0)) FOR [is_default]
GO
ALTER TABLE [tenant].[tenant_account_address] ADD  CONSTRAINT [DF_tenant_account_address_is_active]  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [tenant].[tenant_account_address] ADD  CONSTRAINT [DF_tenant_account_address_is_deleted]  DEFAULT ((0)) FOR [is_deleted]
GO
ALTER TABLE [tenant].[tenant_account_address] ADD  CONSTRAINT [DF_tenant_account_address_created_at]  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [tenant].[tenant_account_address] ADD  CONSTRAINT [DF_tenant_account_address_updated_at]  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [tenant].[tenant_setting] ADD  CONSTRAINT [DF_tenant_setting_is_active]  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [tenant].[tenant_setting] ADD  CONSTRAINT [DF_tenant_setting_is_deleted]  DEFAULT ((0)) FOR [is_deleted]
GO
ALTER TABLE [tenant].[tenant_setting] ADD  CONSTRAINT [DF_tenant_setting_created_at]  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [tenant].[tenant_setting] ADD  CONSTRAINT [DF_tenant_setting_updated_at]  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [auth].[app_user]  WITH CHECK ADD  CONSTRAINT [FK_app_user_created_by] FOREIGN KEY([created_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[app_user] CHECK CONSTRAINT [FK_app_user_created_by]
GO
ALTER TABLE [auth].[app_user]  WITH CHECK ADD  CONSTRAINT [FK_app_user_deleted_by] FOREIGN KEY([deleted_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[app_user] CHECK CONSTRAINT [FK_app_user_deleted_by]
GO
ALTER TABLE [auth].[app_user]  WITH CHECK ADD  CONSTRAINT [FK_app_user_updated_by] FOREIGN KEY([updated_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[app_user] CHECK CONSTRAINT [FK_app_user_updated_by]
GO
ALTER TABLE [auth].[session]  WITH CHECK ADD  CONSTRAINT [FK_session_deleted_by] FOREIGN KEY([deleted_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[session] CHECK CONSTRAINT [FK_session_deleted_by]
GO
ALTER TABLE [auth].[session]  WITH CHECK ADD  CONSTRAINT [FK_session_revoked_by] FOREIGN KEY([revoked_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[session] CHECK CONSTRAINT [FK_session_revoked_by]
GO
ALTER TABLE [auth].[session]  WITH CHECK ADD  CONSTRAINT [FK_session_tenant_id] FOREIGN KEY([tenant_id])
REFERENCES [tenant].[tenant] ([id])
GO
ALTER TABLE [auth].[session] CHECK CONSTRAINT [FK_session_tenant_id]
GO
ALTER TABLE [auth].[tenant_account_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_user_account_id] FOREIGN KEY([account_id])
REFERENCES [tenant].[tenant_account] ([id])
GO
ALTER TABLE [auth].[tenant_account_user] CHECK CONSTRAINT [FK_tenant_account_user_account_id]
GO
ALTER TABLE [auth].[tenant_account_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_user_created_by] FOREIGN KEY([created_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[tenant_account_user] CHECK CONSTRAINT [FK_tenant_account_user_created_by]
GO
ALTER TABLE [auth].[tenant_account_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_user_deleted_by] FOREIGN KEY([deleted_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[tenant_account_user] CHECK CONSTRAINT [FK_tenant_account_user_deleted_by]
GO
ALTER TABLE [auth].[tenant_account_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_user_invited_by] FOREIGN KEY([invited_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[tenant_account_user] CHECK CONSTRAINT [FK_tenant_account_user_invited_by]
GO
ALTER TABLE [auth].[tenant_account_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_user_tenant_id] FOREIGN KEY([tenant_id])
REFERENCES [tenant].[tenant] ([id])
GO
ALTER TABLE [auth].[tenant_account_user] CHECK CONSTRAINT [FK_tenant_account_user_tenant_id]
GO
ALTER TABLE [auth].[tenant_account_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_user_updated_by] FOREIGN KEY([updated_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[tenant_account_user] CHECK CONSTRAINT [FK_tenant_account_user_updated_by]
GO
ALTER TABLE [auth].[tenant_account_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_user_user_id] FOREIGN KEY([user_id])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[tenant_account_user] CHECK CONSTRAINT [FK_tenant_account_user_user_id]
GO
ALTER TABLE [auth].[tenant_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_user_created_by] FOREIGN KEY([created_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[tenant_user] CHECK CONSTRAINT [FK_tenant_user_created_by]
GO
ALTER TABLE [auth].[tenant_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_user_deleted_by] FOREIGN KEY([deleted_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[tenant_user] CHECK CONSTRAINT [FK_tenant_user_deleted_by]
GO
ALTER TABLE [auth].[tenant_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_user_invited_by] FOREIGN KEY([invited_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[tenant_user] CHECK CONSTRAINT [FK_tenant_user_invited_by]
GO
ALTER TABLE [auth].[tenant_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_user_tenant_id] FOREIGN KEY([tenant_id])
REFERENCES [tenant].[tenant] ([id])
GO
ALTER TABLE [auth].[tenant_user] CHECK CONSTRAINT [FK_tenant_user_tenant_id]
GO
ALTER TABLE [auth].[tenant_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_user_updated_by] FOREIGN KEY([updated_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[tenant_user] CHECK CONSTRAINT [FK_tenant_user_updated_by]
GO
ALTER TABLE [auth].[tenant_user]  WITH CHECK ADD  CONSTRAINT [FK_tenant_user_user_id] FOREIGN KEY([user_id])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [auth].[tenant_user] CHECK CONSTRAINT [FK_tenant_user_user_id]
GO
ALTER TABLE [tenant].[tenant]  WITH CHECK ADD  CONSTRAINT [FK_tenant_created_by] FOREIGN KEY([created_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant] CHECK CONSTRAINT [FK_tenant_created_by]
GO
ALTER TABLE [tenant].[tenant]  WITH CHECK ADD  CONSTRAINT [FK_tenant_deleted_by] FOREIGN KEY([deleted_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant] CHECK CONSTRAINT [FK_tenant_deleted_by]
GO
ALTER TABLE [tenant].[tenant]  WITH CHECK ADD  CONSTRAINT [FK_tenant_updated_by] FOREIGN KEY([updated_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant] CHECK CONSTRAINT [FK_tenant_updated_by]
GO
ALTER TABLE [tenant].[tenant_account]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_created_by] FOREIGN KEY([created_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant_account] CHECK CONSTRAINT [FK_tenant_account_created_by]
GO
ALTER TABLE [tenant].[tenant_account]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_deleted_by] FOREIGN KEY([deleted_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant_account] CHECK CONSTRAINT [FK_tenant_account_deleted_by]
GO
ALTER TABLE [tenant].[tenant_account]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_tenant_id] FOREIGN KEY([tenant_id])
REFERENCES [tenant].[tenant] ([id])
GO
ALTER TABLE [tenant].[tenant_account] CHECK CONSTRAINT [FK_tenant_account_tenant_id]
GO
ALTER TABLE [tenant].[tenant_account]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_updated_by] FOREIGN KEY([updated_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant_account] CHECK CONSTRAINT [FK_tenant_account_updated_by]
GO
ALTER TABLE [tenant].[tenant_account_address]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_address_account_id] FOREIGN KEY([account_id])
REFERENCES [tenant].[tenant_account] ([id])
GO
ALTER TABLE [tenant].[tenant_account_address] CHECK CONSTRAINT [FK_tenant_account_address_account_id]
GO
ALTER TABLE [tenant].[tenant_account_address]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_address_created_by] FOREIGN KEY([created_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant_account_address] CHECK CONSTRAINT [FK_tenant_account_address_created_by]
GO
ALTER TABLE [tenant].[tenant_account_address]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_address_deleted_by] FOREIGN KEY([deleted_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant_account_address] CHECK CONSTRAINT [FK_tenant_account_address_deleted_by]
GO
ALTER TABLE [tenant].[tenant_account_address]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_address_tenant_id] FOREIGN KEY([tenant_id])
REFERENCES [tenant].[tenant] ([id])
GO
ALTER TABLE [tenant].[tenant_account_address] CHECK CONSTRAINT [FK_tenant_account_address_tenant_id]
GO
ALTER TABLE [tenant].[tenant_account_address]  WITH CHECK ADD  CONSTRAINT [FK_tenant_account_address_updated_by] FOREIGN KEY([updated_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant_account_address] CHECK CONSTRAINT [FK_tenant_account_address_updated_by]
GO
ALTER TABLE [tenant].[tenant_setting]  WITH CHECK ADD  CONSTRAINT [FK_tenant_setting_created_by] FOREIGN KEY([created_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant_setting] CHECK CONSTRAINT [FK_tenant_setting_created_by]
GO
ALTER TABLE [tenant].[tenant_setting]  WITH CHECK ADD  CONSTRAINT [FK_tenant_setting_deleted_by] FOREIGN KEY([deleted_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant_setting] CHECK CONSTRAINT [FK_tenant_setting_deleted_by]
GO
ALTER TABLE [tenant].[tenant_setting]  WITH CHECK ADD  CONSTRAINT [FK_tenant_setting_tenant_id] FOREIGN KEY([tenant_id])
REFERENCES [tenant].[tenant] ([id])
GO
ALTER TABLE [tenant].[tenant_setting] CHECK CONSTRAINT [FK_tenant_setting_tenant_id]
GO
ALTER TABLE [tenant].[tenant_setting]  WITH CHECK ADD  CONSTRAINT [FK_tenant_setting_updated_by] FOREIGN KEY([updated_by])
REFERENCES [auth].[app_user] ([id])
GO
ALTER TABLE [tenant].[tenant_setting] CHECK CONSTRAINT [FK_tenant_setting_updated_by]
GO
ALTER TABLE [audit].[audit_log]  WITH CHECK ADD  CONSTRAINT [CK_audit_log_action] CHECK  (([action]='import' OR [action]='export' OR [action]='logout' OR [action]='login' OR [action]='delete' OR [action]='update' OR [action]='insert'))
GO
ALTER TABLE [audit].[audit_log] CHECK CONSTRAINT [CK_audit_log_action]
GO
ALTER TABLE [audit].[audit_log]  WITH CHECK ADD  CONSTRAINT [CK_audit_log_new_values_json] CHECK  (([new_values] IS NULL OR isjson([new_values])=(1)))
GO
ALTER TABLE [audit].[audit_log] CHECK CONSTRAINT [CK_audit_log_new_values_json]
GO
ALTER TABLE [audit].[audit_log]  WITH CHECK ADD  CONSTRAINT [CK_audit_log_old_values_json] CHECK  (([old_values] IS NULL OR isjson([old_values])=(1)))
GO
ALTER TABLE [audit].[audit_log] CHECK CONSTRAINT [CK_audit_log_old_values_json]
GO
ALTER TABLE [audit].[audit_log]  WITH CHECK ADD  CONSTRAINT [CK_audit_log_user_type] CHECK  (([user_type] IS NULL OR ([user_type]='tenant_account' OR [user_type]='tenant' OR [user_type]='system')))
GO
ALTER TABLE [audit].[audit_log] CHECK CONSTRAINT [CK_audit_log_user_type]
GO
ALTER TABLE [auth].[app_user]  WITH CHECK ADD  CONSTRAINT [CK_app_user_user_scope] CHECK  (([user_scope]='tenant_account' OR [user_scope]='tenant' OR [user_scope]='system'))
GO
ALTER TABLE [auth].[app_user] CHECK CONSTRAINT [CK_app_user_user_scope]
GO
ALTER TABLE [auth].[session]  WITH CHECK ADD  CONSTRAINT [CK_session_auth_method] CHECK  (([auth_method]='api_key' OR [auth_method]='oauth_microsoft' OR [auth_method]='oauth_google' OR [auth_method]='sso' OR [auth_method]='magic_link' OR [auth_method]='password'))
GO
ALTER TABLE [auth].[session] CHECK CONSTRAINT [CK_session_auth_method]
GO
ALTER TABLE [auth].[session]  WITH CHECK ADD  CONSTRAINT [CK_session_created_from] CHECK  (([created_from]='api' OR [created_from]='desktop' OR [created_from]='mobile_android' OR [created_from]='mobile_ios' OR [created_from]='web'))
GO
ALTER TABLE [auth].[session] CHECK CONSTRAINT [CK_session_created_from]
GO
ALTER TABLE [auth].[session]  WITH CHECK ADD  CONSTRAINT [CK_session_revoked] CHECK  (([is_active]=(1) AND [revoked_at] IS NULL OR [is_active]=(0) AND [revoked_at] IS NOT NULL))
GO
ALTER TABLE [auth].[session] CHECK CONSTRAINT [CK_session_revoked]
GO
ALTER TABLE [auth].[session]  WITH CHECK ADD  CONSTRAINT [CK_session_user_type] CHECK  (([user_type]='tenant_account' OR [user_type]='tenant' OR [user_type]='system'))
GO
ALTER TABLE [auth].[session] CHECK CONSTRAINT [CK_session_user_type]
GO
ALTER TABLE [auth].[tenant_account_user]  WITH CHECK ADD  CONSTRAINT [CK_tenant_account_user_role] CHECK  (([role]='member' OR [role]='admin'))
GO
ALTER TABLE [auth].[tenant_account_user] CHECK CONSTRAINT [CK_tenant_account_user_role]
GO
ALTER TABLE [auth].[tenant_user]  WITH CHECK ADD  CONSTRAINT [CK_tenant_user_role] CHECK  (([role]='viewer' OR [role]='member' OR [role]='admin' OR [role]='owner'))
GO
ALTER TABLE [auth].[tenant_user] CHECK CONSTRAINT [CK_tenant_user_role]
GO
ALTER TABLE [tenant].[tenant]  WITH CHECK ADD  CONSTRAINT [CK_tenant_country] CHECK  (([country] IS NULL OR len([country])=(2)))
GO
ALTER TABLE [tenant].[tenant] CHECK CONSTRAINT [CK_tenant_country]
GO
ALTER TABLE [tenant].[tenant]  WITH CHECK ADD  CONSTRAINT [CK_tenant_features_json] CHECK  (([features_enabled] IS NULL OR isjson([features_enabled])=(1)))
GO
ALTER TABLE [tenant].[tenant] CHECK CONSTRAINT [CK_tenant_features_json]
GO
ALTER TABLE [tenant].[tenant]  WITH CHECK ADD  CONSTRAINT [CK_tenant_max_agents] CHECK  (([max_agents]>(0)))
GO
ALTER TABLE [tenant].[tenant] CHECK CONSTRAINT [CK_tenant_max_agents]
GO
ALTER TABLE [tenant].[tenant]  WITH CHECK ADD  CONSTRAINT [CK_tenant_max_users] CHECK  (([max_users]>(0)))
GO
ALTER TABLE [tenant].[tenant] CHECK CONSTRAINT [CK_tenant_max_users]
GO
ALTER TABLE [tenant].[tenant]  WITH CHECK ADD  CONSTRAINT [CK_tenant_plan_type] CHECK  (([plan_type]='custom' OR [plan_type]='enterprise' OR [plan_type]='professional' OR [plan_type]='starter' OR [plan_type]='trial'))
GO
ALTER TABLE [tenant].[tenant] CHECK CONSTRAINT [CK_tenant_plan_type]
GO
ALTER TABLE [tenant].[tenant]  WITH CHECK ADD  CONSTRAINT [CK_tenant_settings_json] CHECK  (([settings] IS NULL OR isjson([settings])=(1)))
GO
ALTER TABLE [tenant].[tenant] CHECK CONSTRAINT [CK_tenant_settings_json]
GO
ALTER TABLE [tenant].[tenant]  WITH CHECK ADD  CONSTRAINT [CK_tenant_status] CHECK  (([status]='pending' OR [status]='expired' OR [status]='cancelled' OR [status]='suspended' OR [status]='trial' OR [status]='active'))
GO
ALTER TABLE [tenant].[tenant] CHECK CONSTRAINT [CK_tenant_status]
GO
ALTER TABLE [tenant].[tenant_account]  WITH CHECK ADD  CONSTRAINT [CK_tenant_account_custom_fields_json] CHECK  (([custom_fields] IS NULL OR isjson([custom_fields])=(1)))
GO
ALTER TABLE [tenant].[tenant_account] CHECK CONSTRAINT [CK_tenant_account_custom_fields_json]
GO
ALTER TABLE [tenant].[tenant_account_address]  WITH CHECK ADD  CONSTRAINT [CK_tenant_account_address_country] CHECK  (([country] IS NULL OR len([country])=(2)))
GO
ALTER TABLE [tenant].[tenant_account_address] CHECK CONSTRAINT [CK_tenant_account_address_country]
GO
