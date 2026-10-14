from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.filemaintenance.schedule.infrastructure.db_model import PositiveMinutes


class EmployeeCutoffResultModel(Base):
    __tablename__ = "employee_cutoff_results"
    __table_args__ = (
        UniqueConstraint("cutoff_id", "employee_id"),
        {"schema": "payroll"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    cutoff_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payroll.cutoffs.id"),
        nullable=False,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("hr.employees.id"),
        nullable=False,
    )
    scheduled_days: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        nullable=False,
        server_default=text("0"),
    )
    paid_days: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        nullable=False,
        server_default=text("0"),
    )
    regular_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    late_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    undertime_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    absence_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    paid_leave_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    unpaid_leave_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    ordinary_ot_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    rest_day_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    rest_day_ot_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    special_day_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    special_day_ot_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    holiday_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    holiday_ot_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    night_regular_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    night_ot_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    official_business_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    exception_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    employee_confirmation_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    supervisor_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    hr_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    payroll_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'HOLD'"),
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
