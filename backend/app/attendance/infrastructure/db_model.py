from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Any
from uuid import UUID
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from app.core.database import Base
from app.filemaintenance.schedule.infrastructure.db_model import PositiveMinutes

class PunchExceptionModel(Base):
    __tablename__ = "punch_exceptions"
    __table_args__ = (
        CheckConstraint(
            "review_status IN ('OPEN', 'REVIEWED', 'DISMISSED')",
            name="ck_punch_exceptions_review_status",
        ),
        {"schema": "attendance"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    attendance_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("attendance.attendance_records.id", ondelete="SET NULL"), nullable=True,
    )
    punch_action: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(60), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    validation_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    identity_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    client_channel: Mapped[str] = mapped_column(String(20), nullable=False)
    punch_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'OPEN'"))
    reviewed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("identity.users.id", ondelete="SET NULL"), nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AttendanceModel(Base):
    __tablename__ = "attendance_records"
    __table_args__ = {"schema": "attendance"}

    # --- Core Identifiers ---
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("identity.users.id", ondelete="CASCADE"), index=True, nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # --- Shift Snapshot (Prevents historical data corruption) ---
    shift_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    schedule_template_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("schedule.schedule_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    expected_clock_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_clock_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # --- Raw Machine Punches (Audit Trail) ---
    clock_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    clock_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Corrected Punches (Manual / HR Override) ---
    corrected_clock_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    corrected_clock_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Short Rest Breaks ---
    first_break_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    first_break_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    second_break_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    second_break_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # --- Main Meal / Lunch Break ---
    meal_break_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    meal_break_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # --- Overtime Dinner Break ---
    ot_break_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ot_break_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Day Classification ---
    work_type: Mapped[str] = mapped_column(String(10), default="REG", nullable=False)  
    day_type: Mapped[str] = mapped_column(String(10), default="REG", nullable=False)   

    # --- Leaves & Absences ---
    is_absent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    leave_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # e.g., VL, SL, ML, BL
    paid_leave_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- Workflow & Approvals ---
    record_status: Mapped[str] = mapped_column(String(20), default="VALID", nullable=False) 
    correction_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    related_ticket_jo: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    approved_by_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("identity.users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Payroll Computations & Flags ---
    is_manual_entry: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_meal_deduct_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_early_out_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    late_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    undertime_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    calculated_ot_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    overtime_hours: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    regular_overtime_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    regular_overtime_hours: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    night_differential_overtime_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    night_differential_overtime_hours: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    night_differential_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    night_differential_hours: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    overtime_request_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    requested_regular_overtime_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    requested_night_differential_overtime_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    requested_night_differential_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    overtime_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_regular_overtime_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    approved_night_differential_overtime_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    approved_night_differential_minutes: Mapped[int] = mapped_column(default=0, nullable=False)
    overtime_approved_by_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("identity.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    overtime_approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- FINAL PAYROLL BASIS (Supervisor Approved) ---
    approved_hours_worked: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    approved_ot_start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_ot_end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_ot_worked: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    approved_night_diff: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- Audit Trail & Geofencing ---
    punch_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    
    created_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_by: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OvertimeApplicationModel(Base):
    __tablename__ = "overtime_applications"
    __table_args__ = (
        CheckConstraint(
            "requested_end_at > requested_start_at",
            name="ck_overtime_applications_requested_period",
        ),
        CheckConstraint(
            "requested_minutes >= 0 AND potential_ot_minutes >= 0 "
            "AND (system_validated_minutes IS NULL OR system_validated_minutes >= 0) "
            "AND (supervisor_approved_minutes IS NULL OR supervisor_approved_minutes >= 0) "
            "AND (final_payable_minutes IS NULL OR final_payable_minutes >= 0)",
            name="ck_overtime_applications_nonnegative_minutes",
        ),
        CheckConstraint(
            "final_payable_minutes IS NULL OR supervisor_approved_minutes IS NULL "
            "OR final_payable_minutes <= supervisor_approved_minutes",
            name="ck_overtime_applications_final_not_above_approved",
        ),
        UniqueConstraint("application_no", name="uq_overtime_applications_application_no"),
        {"schema": "attendance"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    application_no: Mapped[str] = mapped_column(String(50), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("hr.employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attendance_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("attendance.attendance_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    daily_result_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    authorization_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    potential_ot_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    system_validated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supervisor_approved_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_payable_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overtime_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    work_accomplished: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    workflow_instance_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'DRAFT'"),
        index=True,
    )
    payroll_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
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
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
class OfficialBusinessRequestModel(Base):
    __tablename__ = "official_business_requests"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="official_business_requests_check"),
        UniqueConstraint("request_no", name="official_business_requests_request_no_key"),
        {"schema": "attendance"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    request_no: Mapped[str] = mapped_column(String(50), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("hr.employees.id"),
        nullable=False,
        index=True,
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    destination: Mapped[str] = mapped_column(String(300), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    geofence_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("location.geofences.id"),
        nullable=True,
    )
    jo_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # fleet.vehicles and workflow.instances are not ORM-mapped; their FKs live in the SQL migration.
    vehicle_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    requested_minutes: Mapped[int] = mapped_column(PositiveMinutes(), nullable=False)
    approved_minutes: Mapped[int | None] = mapped_column(PositiveMinutes(), nullable=True)
    workflow_instance_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    payroll_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
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
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
