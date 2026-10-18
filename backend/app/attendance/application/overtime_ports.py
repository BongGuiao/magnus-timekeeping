from datetime import date
from typing import Any, Optional, Protocol, Sequence
from uuid import UUID

from app.attendance.domain.entities.attendance_employee import AttendanceEmployee
from app.attendance.domain.entities.overtime import (
    OvertimeApplication,
    OvertimeApplicationRecord,
    OvertimeAttendance,
    OvertimeCutoff,
)


class OvertimeRepository(Protocol):
    async def get_active_employee_id_for_user(self, user_id: UUID) -> Optional[UUID]: ...

    async def get_user_id_for_employee(self, employee_id: UUID) -> Optional[UUID]: ...

    async def get_current_cutoff(self, employee_id: UUID, today: date) -> Optional[OvertimeCutoff]: ...

    async def get_cutoff_for_employee_on_date(
        self,
        employee_id: UUID,
        work_date: date,
    ) -> Optional[OvertimeCutoff]: ...

    async def list_completed_attendance_in_period(
        self, user_id: UUID, period_start: date, period_end: date
    ) -> list[OvertimeAttendance]: ...

    async def list_employee_attendance_in_range(
        self,
        employee_id: UUID,
        from_date: date,
        to_date: date,
        *,
        lock_for_update: bool = False,
    ) -> list[OvertimeAttendance]: ...

    async def list_break_rules_for_template(
        self, schedule_template_id: UUID
    ) -> list[dict[str, Any]]: ...

    async def lock_completed_attendance(
        self, attendance_id: UUID, user_id: UUID
    ) -> Optional[tuple[OvertimeAttendance, AttendanceEmployee]]: ...

    async def lock_owned_application(
        self, application_id: UUID, user_id: UUID
    ) -> Optional[OvertimeApplicationRecord]: ...

    async def has_open_application(
        self,
        attendance_id: UUID,
        overtime_type: Optional[str] = None,
        exclude_application_id: Optional[UUID] = None,
    ) -> bool: ...

    async def add_application(self, application: OvertimeApplication) -> OvertimeApplication: ...

    async def save_application(self, application: OvertimeApplication) -> None: ...

    async def save_attendance(self, attendance: OvertimeAttendance) -> None: ...

    async def list_applications_for_attendance(
        self, attendance_id: UUID
    ) -> Sequence[OvertimeApplication]:
        """Active applications, newest first."""
        ...

    async def list_applications_for_user(self, user_id: UUID) -> list[OvertimeApplicationRecord]: ...

    async def list_pending_applications(
        self, supervisor_employee_id: Optional[UUID]
    ) -> list[OvertimeApplicationRecord]:
        """Pending applications; scoped to a supervisor's team unless the id is None."""
        ...

    async def lock_pending_application(
        self, application_id: UUID, supervisor_employee_id: Optional[UUID]
    ) -> Optional[OvertimeApplicationRecord]: ...


class OvertimeUnitOfWork(Protocol):
    overtime: OvertimeRepository

    async def __aenter__(self) -> "OvertimeUnitOfWork": ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
