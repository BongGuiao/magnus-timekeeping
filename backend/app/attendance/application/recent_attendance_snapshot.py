from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.attendance.domain.entities.overtime import OvertimeType


class RecentOvertimeApplication(BaseModel):
    id: UUID
    application_no: str
    overtime_type: OvertimeType
    requested_minutes: int
    supervisor_approved_minutes: int | None
    final_payable_minutes: int | None
    status: str


class RecentAttendanceItem(BaseModel):
    attendance_id: UUID | None = None
    schedule_template_id: UUID | None = None
    overtime_applications: list[RecentOvertimeApplication] = Field(default_factory=list)
    date: str
    expected_time_in: str | None = None
    expected_time_out: str | None = None
    time_in: str | None = None
    time_out: str | None = None
    minutes_worked: int | None = Field(default=None, ge=0)
    late_minutes: int = 0
    undertime_minutes: int = 0
    excess_minutes_break: int = 0
    calculated_ot_minutes: int = 0
    overtime_hours: float = 0
    regular_overtime_minutes: int = 0
    regular_overtime_hours: float = 0
    night_differential_overtime_minutes: int = 0
    night_differential_overtime_hours: float = 0
    night_differential_minutes: int = 0
    night_differential_hours: float = 0
    overtime_request_status: Literal["PENDING", "APPROVED", "REJECTED"] | None = None
    requested_regular_overtime_minutes: int = 0
    requested_night_differential_overtime_minutes: int = 0
    requested_night_differential_minutes: int = 0
    approved_regular_overtime_minutes: int = 0
    approved_night_differential_overtime_minutes: int = 0
    approved_night_differential_minutes: int = 0
    is_late: bool = False
    is_undertime: bool = False
    status: Literal["present", "late", "no-login", "no-logout", "on-leave"]


class RecentAttendanceSnapshot(BaseModel):
    """Read model served to the dashboard; produced by the snapshot task and cached."""

    records: list[RecentAttendanceItem]
    weekly_hours_worked: float = 0
    weekly_minutes_worked: int = Field(default=0, ge=0)
    missed_clock_ins_this_month: int = 0
    refreshed_at: str
