"""SQLAlchemy models — schema `tenant`."""

from mtf.tenant.models.mailbox import Mailbox
from mtf.tenant.models.mailbox_credential import MailboxCredential
from mtf.tenant.models.tenant import Tenant
from mtf.tenant.models.tenant_account import TenantAccount
from mtf.tenant.models.tenant_account_address import TenantAccountAddress

__all__ = ["Mailbox", "MailboxCredential", "Tenant", "TenantAccount", "TenantAccountAddress"]


