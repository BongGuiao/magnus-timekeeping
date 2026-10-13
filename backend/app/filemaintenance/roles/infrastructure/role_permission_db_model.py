from uuid import UUID

from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RolePermissionModel(Base):
    __tablename__ = "role_permissions"
    __table_args__ = {"schema": "identity"}

    role_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("identity.roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("identity.permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
