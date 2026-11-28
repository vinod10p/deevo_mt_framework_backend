"""SQLAlchemy model — ``auth.permission``."""

from __future__ import annotations

from sqlalchemy import Integer, String, Unicode, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from mtf.shared.database import Base
from mtf.shared.model_columns import StandardColumnsMixin, flag, ulid_pk


class Permission(StandardColumnsMixin, Base):
    """Catalog of grantable actions.

    ``code`` is ``<resource_type>.<resource_code>.<action>``; live uniqueness is
    ``(user_scope, code)`` (``UQ_permission_scope_code``). ``UQ_permission_id_user_scope``
    lets ``role_permission`` enforce a matching ``user_scope`` through a composite FK.
    """

    __tablename__ = "permission"
    __table_args__ = (
        UniqueConstraint("id", "user_scope", name="UQ_permission_id_user_scope"),
        {"schema": "auth"},
    )

    id: Mapped[str] = ulid_pk()
    code: Mapped[str] = mapped_column(String(150), nullable=False)
    #: ``CK_permission_resource_type``: menu | screen | api
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_code: Mapped[str] = mapped_column(String(100), nullable=False)
    #: ``CK_permission_action``: view | create | update | delete | export | import | approve
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    #: ``CK_permission_user_scope``: system | tenant | tenant_account
    user_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Unicode(300), nullable=True)
    #: ``CK_permission_module_code_upper``: non-empty, stored uppercase
    module_code: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_name: Mapped[str] = mapped_column(Unicode(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    #: ``CK_permission_system_not_grantable``: system scope => 0
    is_tenant_grantable: Mapped[bool] = flag(default=True)

    def __repr__(self) -> str:
        return f"<Permission id={self.id!r} code={self.code!r} user_scope={self.user_scope!r}>"
