from datetime import date, datetime
from typing import Optional, Protocol
from uuid import UUID

from app.attendance.domain.entities.attendance_review import (
    ReviewableAttendance,
    ReviewableAttendanceRecord,
    UnresolvedAttendanceRouting,
)


class AttendanceReviewRepository(Protocol):
    async def list_invalid(
        self, supervisor_employee_id: Optional[UUID], today: date, actor_employee_id: Optional[UUID] = None
    ) -> list[ReviewableAttendanceRecord]:
        """Invalid attendance; scoped to a supervisor's current team unless the id is None."""
        ...

    async def lock_invalid(
        self, attendance_id: UUID, supervisor_employee_id: Optional[UUID], today: date,
        actor_employee_id: Optional[UUID] = None,
    ) -> Optional[ReviewableAttendanceRecord]: ...

    async def list_unresolved_routes(self) -> list[UnresolvedAttendanceRouting]: ...

    async def retry_unresolved_route(self, attendance_id: UUID, actor_id: UUID, today: date) -> Optional[str]: ...

    async def save_review(self, attendance: ReviewableAttendance) -> None: ...

    async def require_attendance_open(self, employee_id: UUID, work_date: date, now: datetime) -> None:
        """Raises CutoffDeadlineError when the work date belongs to a closed payroll cutoff."""
        ...


class AttendanceReviewUnitOfWork(Protocol):
    review: AttendanceReviewRepository

    async def __aenter__(self) -> "AttendanceReviewUnitOfWork": ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
