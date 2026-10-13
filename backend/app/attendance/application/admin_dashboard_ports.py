from datetime import date
from typing import Protocol
from uuid import UUID

from app.attendance.domain.entities.admin_dashboard import (
    PendingLeaveSummary,
    TeamAttendanceDay,
    WeeklyAttendanceSample,
)


class AdminDashboardRepository(Protocol):
    async def list_team_attendance(
        self, supervisor_employee_id: UUID, today: date, month_start: date
    ) -> list[TeamAttendanceDay]:
        """Valid attendance this month for employees currently supervised by the given employee."""
        ...

    async def list_pending_leaves(self) -> list[PendingLeaveSummary]: ...

    async def list_weekly_attendance(self, week_start: date, today: date) -> list[WeeklyAttendanceSample]:
        """Valid attendance of every active employee from the week start through today."""
        ...


class AdminDashboardUnitOfWork(Protocol):
    dashboard: AdminDashboardRepository

    async def __aenter__(self) -> "AdminDashboardUnitOfWork": ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
