from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from app.attendance.domain.entities.attendance_employee import AttendanceEmployee


@dataclass
class TeamAttendanceDay:
    employee: AttendanceEmployee
    supervisor: AttendanceEmployee
    work_date: date
    clock_in_at: Optional[datetime]
    clock_out_at: Optional[datetime]
    expected_clock_out_at: Optional[datetime]
    is_absent: bool
    leave_type: Optional[str]


@dataclass
class AttendanceException:
    employee: AttendanceEmployee
    supervisor: AttendanceEmployee
    work_date: date
    time_in: Optional[datetime]
    time_out: Optional[datetime]


@dataclass
class PendingLeaveSummary:
    id: UUID
    application_no: str
    employee: AttendanceEmployee
    leave_type: str
    start_at: datetime
    end_at: datetime
    requested_minutes: int
    status: str


@dataclass
class WeeklyAttendanceSample:
    employee: AttendanceEmployee
    clock_in_at: Optional[datetime]
    clock_out_at: Optional[datetime]
    punch_metadata: Optional[dict[str, Any]] = None


@dataclass
class EmployeeWeeklyHours:
    employee: AttendanceEmployee
    minutes_worked: int

    @property
    def hours_worked(self) -> float:
        return round(self.minutes_worked / 60, 2)


@dataclass
class AdminDashboard:
    no_login: list[AttendanceException] = field(default_factory=list)
    no_logout: list[AttendanceException] = field(default_factory=list)
    pending_leaves: list[PendingLeaveSummary] = field(default_factory=list)
    weekly_hours: list[EmployeeWeeklyHours] = field(default_factory=list)
    refreshed_at: Optional[datetime] = None
