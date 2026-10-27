from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.attendance.application.recent_attendance_snapshot import RecentAttendanceItem
from app.attendance.domain.entities.overtime import OvertimeType as OvertimeApplicationType


class OvertimeApplicationInputSchema(BaseModel):
    overtime_type: OvertimeApplicationType
    requested_start_at: AwareDatetime | None = None
    requested_end_at: AwareDatetime | None = None
    requested_minutes: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=5000)
    work_accomplished: str | None = Field(default=None, max_length=5000)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def normalize_text(self) -> "OvertimeApplicationInputSchema":
        if self.overtime_type == "NIGHT_DIFFERENTIAL":
            raise ValueError(
                "Night-differential hours are calculated and approved automatically; "
                "a separate application is not required."
            )
        if (self.requested_start_at is None) != (self.requested_end_at is None):
            raise ValueError("Requested start and end must be supplied together.")
        if self.requested_start_at is not None and self.requested_end_at is not None:
            if self.requested_end_at <= self.requested_start_at:
                raise ValueError("Requested end must be after requested start.")
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("reason cannot be blank.")
        if self.work_accomplished is not None:
            self.work_accomplished = self.work_accomplished.strip() or None
        return self


class OvertimeApplicationDecisionSchema(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    supervisor_approved_minutes: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="forbid")


class OvertimeApplicationSchema(BaseModel):
    id: UUID
    application_no: str
    attendance_record_id: UUID
    employee_id: UUID
    employee_code: str
    employee_name: str
    attendance_date: date
    requested_start_at: datetime
    requested_end_at: datetime
    potential_ot_minutes: int
    requested_minutes: int
    system_validated_minutes: int | None
    supervisor_approved_minutes: int | None
    final_payable_minutes: int | None
    overtime_type: OvertimeApplicationType
    reason: str
    work_accomplished: str | None
    validation_status: str | None
    status: str
    payroll_posted: bool


class OvertimeCutoffSchema(BaseModel):
    cutoff_code: str
    period_start: date
    period_end: date


class OvertimeAttendanceOptionsSchema(BaseModel):
    cutoff: OvertimeCutoffSchema
    records: list[RecentAttendanceItem]


class AttendanceRangeRecalculationInputSchema(BaseModel):
    scope: Literal["own", "team", "employee"]
    employee_id: UUID | None = None
    from_date: date
    to_date: date
    dry_run: bool = True

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_date_range(self) -> "AttendanceRangeRecalculationInputSchema":
        if self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date.")
        if self.scope == "employee" and self.employee_id is None:
            raise ValueError("employee_id is required for employee scope.")
        if self.scope != "employee" and self.employee_id is not None:
            raise ValueError("employee_id is only allowed for employee scope.")
        return self


class AttendanceBreakCalculationDetailSchema(BaseModel):
    break_slot: str
    punch_out_at: datetime | None
    punch_in_at: datetime | None
    duration_minutes: int | None
    allowance_minutes: int | None
    excess_minutes: int

    model_config = ConfigDict(from_attributes=True)


class AttendanceRangeRecalculationItemSchema(BaseModel):
    attendance_id: UUID
    work_date: date
    status: Literal["PREVIEW", "UPDATED", "UNCHANGED", "SKIPPED"]
    reason: str | None
    previous_expected_clock_in_at: datetime | None
    previous_expected_clock_out_at: datetime | None
    actual_clock_in_at: datetime | None
    actual_clock_out_at: datetime | None
    expected_clock_in_at: datetime | None
    expected_clock_out_at: datetime | None
    regular_overtime_minutes: int
    night_differential_overtime_minutes: int
    calculated_ot_minutes: int
    night_differential_minutes: int
    regular_night_differential_minutes: int
    previous_late_minutes: int
    late_minutes: int
    undertime_minutes: int
    excess_minutes_break: int = 0
    minutes_worked: int | None = None
    break_calculation_details: list[AttendanceBreakCalculationDetailSchema] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AttendanceRangeRecalculationSchema(BaseModel):
    employee_id: UUID
    from_date: date
    to_date: date
    dry_run: bool
    preview_count: int
    updated_count: int
    unchanged_count: int
    skipped_count: int
    records: list[AttendanceRangeRecalculationItemSchema]

    model_config = ConfigDict(from_attributes=True)
