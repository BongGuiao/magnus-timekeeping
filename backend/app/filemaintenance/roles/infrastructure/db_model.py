from datetime import date
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserRoleModel(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_user_role_effective_dates",
        ),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    role_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.roles.id"), nullable=False
    )
    company_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.companies.id"), nullable=True
    )
    org_unit_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.org_units.id"), nullable=True
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    assigned_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True
    )
