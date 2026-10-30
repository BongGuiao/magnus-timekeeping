from uuid import UUID
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LocationType(Base):
    __tablename__ = "location_types"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(location_type)) > 0",
            name="ck_location_types_code_not_empty",
        ),
        CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_location_types_display_name_not_empty",
        ),
        Index(
            "uq_location_types_single_default_per_company",
            "company_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        {"schema": "core"},
    )

    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.companies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    location_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("identity.users.id"),
        nullable=True,
    )
