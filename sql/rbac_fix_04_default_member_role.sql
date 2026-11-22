/*
    rbac_fix_04_default_member_role.sql
    Database: deevo_app_dev2
    Requires: auth.tenant_user, auth_rbac_backfill_v3.sql (user_role)

    Per-user opt-out of the automatic tenant_member assignment.

    auth.tenant_user.default_member_role_enabled
        1 (default)  member/viewer membership gets platform tenant_member
        0            member/viewer gets no template role; only roles
                     assigned through Role Admin apply
    Owner/admin always get tenant_admin; the stored value is kept and
    applies again if the user is later demoted.

    The column is changed only through
    PATCH /api/tenant/users/{user_id}/default-member-role, which
    reconciles auth.user_role in the same transaction. Do not flip it
    by hand without also revoking or restoring tenant_member.

    Existing rows get 1, so current assignments do not change.

    Apply AFTER rbac_fix_03_screens_flag.sql, as deevo. Safe to rerun.
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

USE [deevo_app_dev2];
GO

IF COL_LENGTH('auth.tenant_user', 'default_member_role_enabled') IS NULL
    ALTER TABLE auth.tenant_user
        ADD default_member_role_enabled bit NOT NULL
            CONSTRAINT DF_tenant_user_default_member_role_enabled DEFAULT (1)
            WITH VALUES;
GO
