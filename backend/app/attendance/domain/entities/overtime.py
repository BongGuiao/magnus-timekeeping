from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from app.attendance.domain.entities.attendance_employee import AttendanceEmployee

REGULAR_OVERTIME = "REGULAR_OVERTIME"
NIGHT_DIFFERENTIAL_OVERTIME = "NIGHT_DIFFERENTIAL_OVERTIME"
NIGHT_DIFFERENTIAL = "NIGHT_DIFFERENTIAL"

OvertimeType = Literal["REGULAR_OVERTIME", "NIGHT_DIFFERENTIAL_OVERTIME", "NIGHT_DIFFERENTIAL"]


@dataclass
class OvertimeCutoff:
    cutoff_code: str
    period_start: date
    period_end: date
    employee_review_deadline: datetime | None = None
    supervisor_deadline: datetime | None = None
    hr_deadline: datetime | None = None


@dataclass
class OvertimeAttendance:
    id: UUID
    user_id: UUID
    work_date: date
    schedule_template_id: Optional[UUID] = None
    record_status: str = "VALID"
    is_locked: bool = False
    expected_clock_in_at: Optional[datetime] = None
    expected_clock_out_at: Optional[datetime] = None
    clock_in_at: Optional[datetime] = None
    clock_out_at: Optional[datetime] = None
    corrected_clock_in_at: Optional[datetime] = None
    corrected_clock_out_at: Optional[datetime] = None
    first_break_out_at: Optional[datetime] = None
    first_break_in_at: Optional[datetime] = None
    meal_break_out_at: Optional[datetime] = None
    meal_break_in_at: Optional[datetime] = None
    second_break_out_at: Optional[datetime] = None
    second_break_in_at: Optional[datetime] = None
    ot_break_out_at: Optional[datetime] = None
    ot_break_in_at: Optional[datetime] = None
    punch_metadata: Optional[dict[str, Any]] = None
    calculated_ot_minutes: int = 0
    overtime_hours: Decimal = Decimal(0)
    late_minutes: int = 0
    undertime_minutes: int = 0
    regular_overtime_minutes: int = 0
    regular_overtime_hours: Decimal = Decimal(0)
    night_differential_overtime_minutes: int = 0
    night_differential_overtime_hours: Decimal = Decimal(0)
    night_differential_minutes: int = 0
    night_differential_hours: Decimal = Decimal(0)
    overtime_request_status: Optional[str] = None
    requested_regular_overtime_minutes: int = 0
    requested_night_differential_overtime_minutes: int = 0
    requested_night_differential_minutes: int = 0
    overtime_requested_at: Optional[datetime] = None
    approved_regular_overtime_minutes: int = 0
    approved_night_differential_overtime_minutes: int = 0
    approved_night_differential_minutes: int = 0
    overtime_approved_by_id: Optional[UUID] = None
    overtime_approved_at: Optional[datetime] = None
    approved_ot_worked: Optional[float] = None
    approved_night_diff: Optional[float] = None

    @property
    def effective_clock_in(self) -> Optional[datetime]:
        return self.corrected_clock_in_at or self.clock_in_at

    @property
    def effective_clock_out(self) -> Optional[datetime]:
        return self.corrected_clock_out_at or self.clock_out_at


@dataclass
class OvertimeApplication:
    application_no: str
    employee_id: UUID
    attendance_record_id: UUID
    attendance_date: date
    requested_start_at: datetime
    requested_end_at: datetime
    potential_ot_minutes: int
    requested_minutes: int
    overtime_type: str
    reason: str
    status: str = "PENDING"
    system_validated_minutes: Optional[int] = None
    supervisor_approved_minutes: Optional[int] = None
    final_payable_minutes: Optional[int] = None
    work_accomplished: Optional[str] = None
    validation_status: Optional[str] = None
    payroll_posted: bool = False
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None
    row_version: int = 1
    id: Optional[UUID] = None


@dataclass
class OvertimeApplicationRecord:
    """An application together with the attendance and employee it belongs to."""

    application: OvertimeApplication
    attendance: OvertimeAttendance
    employee: AttendanceEmployee
