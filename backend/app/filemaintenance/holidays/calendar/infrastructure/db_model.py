from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HolidayCalendarModel(Base):
    __tablename__ = "holiday_calendars"
    __table_args__ = (
        CheckConstraint(
            "effective_year BETWEEN 2000 AND 2200",
            name="ck_holiday_calendars_effective_year",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'CLOSED')",
            name="ck_holiday_calendars_status",
        ),
        UniqueConstraint(
            "company_id",
            "calendar_code",
            "effective_year",
            name="uq_holiday_calendars_company_code_year",
        ),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.companies.id"),
        nullable=False,
    )
    calendar_code: Mapped[str] = mapped_column(String(30), nullable=False)
    calendar_name: Mapped[str] = mapped_column(String(150), nullable=False)
    effective_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'DRAFT'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    row_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )