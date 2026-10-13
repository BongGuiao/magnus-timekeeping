from datetime import date
from typing import Optional, Protocol
from uuid import UUID

from app.attendance.domain.entities.attendance_review import (
    ReviewableAttendance,
    ReviewableAttendanceRecord,
)


class AttendanceReviewRepository(Protocol):
    async def list_invalid(
        self, supervisor_employee_id: Optional[UUID], today: date
    ) -> list[ReviewableAttendanceRecord]:
        """Invalid attendance; scoped to a supervisor's current team unless the id is None."""
        ...

    async def lock_invalid(
        self, attendance_id: UUID, supervisor_employee_id: Optional[UUID], today: date
    ) -> Optional[ReviewableAttendanceRecord]: ...

    async def save_review(self, attendance: ReviewableAttendance) -> None: ...


class AttendanceReviewUnitOfWork(Protocol):
    review: AttendanceReviewRepository

    async def __aenter__(self) -> "AttendanceReviewUnitOfWork": ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
