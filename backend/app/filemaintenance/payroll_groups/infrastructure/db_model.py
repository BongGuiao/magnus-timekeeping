from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PayrollGroupModel(Base):
    __tablename__ = "payroll_groups"
    __table_args__ = (
        CheckConstraint(
            "pay_frequency IN ('WEEKLY', 'BIWEEKLY', 'SEMIMONTHLY', 'MONTHLY')",
            name="ck_payroll_groups_pay_frequency",
        ),
        CheckConstraint(
            "rate_type IN ('MONTHLY', 'DAILY', 'HOURLY')",
            name="ck_payroll_groups_rate_type",
        ),
        CheckConstraint(
            "standard_minutes_per_day > 0",
            name="ck_payroll_groups_standard_minutes_per_day",
        ),
        CheckConstraint(
            "annual_divisor IS NULL OR annual_divisor > 0",
            name="ck_payroll_groups_annual_divisor",
        ),
        CheckConstraint(
            "rounding_minutes > 0",
            name="ck_payroll_groups_rounding_minutes",
        ),
        UniqueConstraint(
            "company_id",
            "payroll_group_code",
            name="uq_payroll_groups_company_code",
        ),
        {"schema": "payroll"},
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
    payroll_group_code: Mapped[str] = mapped_column(String(30), nullable=False)
    payroll_group_name: Mapped[str] = mapped_column(String(100), nullable=False)
    pay_frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    rate_type: Mapped[str] = mapped_column(String(20), nullable=False)
    standard_minutes_per_day: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("480"),
    )
    annual_divisor: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    rounding_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    holiday_calendar_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.holiday_calendars.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'ACTIVE'"),
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
        onupdate=func.now(),
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
