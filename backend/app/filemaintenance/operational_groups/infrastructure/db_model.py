from uuid import UUID
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OperationalGroupModel(Base):
    __tablename__ = "operational_groups"
    __table_args__ = (
        CheckConstraint(
            "operational_group ~ '^[A-Z0-9_-]+$'",
            name="ck_operational_groups_code",
        ),
        CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_operational_groups_display_name",
        ),
        CheckConstraint("sort_order >= 0", name="ck_operational_groups_sort_order"),
        {"schema": "core"},
    )

    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.companies.id", ondelete="CASCADE"), primary_key=True
    )
    operational_group: Mapped[str] = mapped_column(String(30), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("identity.users.id", name="fk_operational_groups_deleted_by"), nullable=True,
    )
