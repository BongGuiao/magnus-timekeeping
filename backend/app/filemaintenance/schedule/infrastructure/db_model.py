from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    SmallInteger,
    String,
    Time,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.core.database import Base


class PositiveMinutes(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_: object) -> str:
        return "core.positive_minutes"


class ScheduleTemplateModel(Base):
    __tablename__ = "schedule_templates"
    __table_args__ = (
        CheckConstraint(
            "schedule_type IN ('FIXED', 'FLEXIBLE', 'SHIFTING', 'OVERNIGHT', 'SPLIT', "
            "'COMPRESSED', 'FIELD', 'ON_CALL')",
            name="ck_schedule_templates_schedule_type",
        ),
        UniqueConstraint(
            "company_id",
            "schedule_code",
            name="uq_schedule_templates_company_code",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_schedule_templates_effective_dates",
        ),
        {"schema": "schedule"},
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
    schedule_code: Mapped[str] = mapped_column(String(30), nullable=False)
    schedule_name: Mapped[str] = mapped_column(String(150), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    required_minutes: Mapped[int] = mapped_column(PositiveMinutes(), nullable=False)
    grace_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    grace_method: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'NONE'"),
    )
    is_overnight: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    ot_eligible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    pre_shift_ot_allowed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    minimum_ot_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    holiday_calendar_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.holiday_calendars.id"),
        nullable=True,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
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


class ScheduleSegmentModel(Base):
    __tablename__ = "schedule_segments"
    __table_args__ = (
        CheckConstraint(
            "segment_type IN ('WORK', 'PAID_BREAK', 'UNPAID_BREAK')",
            name="ck_schedule_segments_segment_type",
        ),
        CheckConstraint(
            "end_day_offset BETWEEN 0 AND 2",
            name="ck_schedule_segments_end_day_offset",
        ),
        UniqueConstraint(
            "schedule_template_id",
            "segment_sequence",
            name="uq_schedule_segments_template_sequence",
        ),
        CheckConstraint(
            "(break_slot IS NULL AND work_segment_sequence IS NULL AND break_minutes = 0) "
            "OR (break_slot IS NOT NULL AND segment_type IN ('PAID_BREAK', 'UNPAID_BREAK') "
            "AND break_slot IN ('FIRST_BREAK', 'MEAL_BREAK', 'SECOND_BREAK') "
            "AND work_segment_sequence IS NOT NULL AND break_minutes > 0)",
            name="ck_schedule_segments_break_rule",
        ),
        Index(
            "uq_schedule_segments_break_slot", "schedule_template_id", "break_slot",
            unique=True, postgresql_where=text("break_slot IS NOT NULL"),
        ),
        {"schema": "schedule"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    schedule_template_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedule.schedule_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    segment_sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    segment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    break_slot: Mapped[str | None] = mapped_column(String(30), nullable=True)
    work_segment_sequence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    break_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_day_offset: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default=text("0"),
    )
    paid_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )
    punch_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    auto_deduct: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    flex_start_minutes: Mapped[int] = mapped_column(
        PositiveMinutes(),
        nullable=False,
        server_default=text("0"),
    )


class RestDayPatternModel(Base):
    __tablename__ = "rest_day_patterns"
    __table_args__ = (
        CheckConstraint(
            "cycle_length_days BETWEEN 1 AND 366",
            name="ck_rest_day_patterns_cycle_length",
        ),
        UniqueConstraint("pattern_code", name="uq_rest_day_patterns_pattern_code"),
        {"schema": "schedule"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    pattern_code: Mapped[str] = mapped_column(String(30), nullable=False)
    pattern_name: Mapped[str] = mapped_column(String(100), nullable=False)
    cycle_length_days: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )


class RestDayPatternDayModel(Base):
    __tablename__ = "rest_day_pattern_days"
    __table_args__ = (
        {"schema": "schedule"},
    )

    pattern_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedule.rest_day_patterns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    cycle_day_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    is_workday: Mapped[bool] = mapped_column(Boolean, nullable=False)
    schedule_template_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedule.schedule_templates.id"),
        nullable=True,
    )


class EmployeeScheduleAssignmentModel(Base):
    __tablename__ = "employee_schedule_assignments"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_employee_schedule_assignments_effective_dates",
        ),
        {"schema": "schedule"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("hr.employees.id"),
        nullable=False,
    )
    schedule_template_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedule.schedule_templates.id"),
        nullable=False,
    )
    rest_day_pattern_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedule.rest_day_patterns.id"),
        nullable=True,
    )
    assignment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("identity.users.id"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
