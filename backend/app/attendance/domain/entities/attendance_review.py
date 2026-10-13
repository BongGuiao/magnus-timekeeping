from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from app.attendance.domain.entities.attendance_employee import AttendanceEmployee
from app.attendance.domain.exceptions import RuleViolationError


@dataclass
class ReviewableAttendance:
    id: UUID
    user_id: UUID
    work_date: date
    record_status: str
    clock_in_at: Optional[datetime] = None
    clock_out_at: Optional[datetime] = None
    corrected_clock_in_at: Optional[datetime] = None
    corrected_clock_out_at: Optional[datetime] = None
    approved_by_id: Optional[UUID] = None
    approved_at: Optional[datetime] = None

    @property
    def effective_clock_in(self) -> Optional[datetime]:
        return self.corrected_clock_in_at or self.clock_in_at

    @property
    def effective_clock_out(self) -> Optional[datetime]:
        return self.corrected_clock_out_at or self.clock_out_at

    def approve(self, approver_id: UUID, at: datetime) -> None:
        if self.record_status != "INVALID":
            raise RuleViolationError("Only invalid attendance can be approved.")
        self.record_status = "VALID"
        self.approved_by_id = approver_id
        self.approved_at = at


@dataclass
class ReviewableAttendanceRecord:
    attendance: ReviewableAttendance
    employee: AttendanceEmployee
