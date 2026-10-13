from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable
from uuid import UUID

from app.attendance.application.admin_dashboard_ports import AdminDashboardUnitOfWork
from app.attendance.application.clock import ph_today, utc_now
from app.attendance.application.worked_minutes import net_worked_minutes
from app.attendance.domain.admin_dashboard_rules import classify_attendance_exceptions
from app.attendance.domain.entities.admin_dashboard import (
    AdminDashboard,
    EmployeeWeeklyHours,
    WeeklyAttendanceSample,
)
from app.core.generics.uc_base import BaseUseCase


def total_weekly_minutes(samples: Iterable[WeeklyAttendanceSample]) -> list[EmployeeWeeklyHours]:
    """Net worked minutes per employee, using the same formula as the employee's own snapshot."""
    totals: dict[UUID, EmployeeWeeklyHours] = {}
    for sample in samples:
        minutes = net_worked_minutes(sample.clock_in_at, sample.clock_out_at, sample.punch_metadata)
        if minutes is None:
            continue
        employee_total = totals.setdefault(sample.employee.id, EmployeeWeeklyHours(sample.employee, 0))
        employee_total.minutes_worked += minutes
    return sorted(totals.values(), key=lambda total: total.employee.employee_no)


@dataclass
class GetAdminDashboardInput:
    supervisor_employee_id: UUID


class GetAdminDashboardUseCase(BaseUseCase[AdminDashboard]):
    def __init__(self, uow: AdminDashboardUnitOfWork, clock: Callable[[], datetime] = utc_now):
        self._uow = uow
        self._clock = clock

    async def _execute(self, data: GetAdminDashboardInput) -> AdminDashboard:
        now = self._clock()
        today = ph_today(now)
        month_start = today.replace(day=1)
        week_start = today - timedelta(days=today.weekday())
        async with self._uow as uow:
            team_days = await uow.dashboard.list_team_attendance(
                data.supervisor_employee_id, today, month_start
            )
            pending_leaves = await uow.dashboard.list_pending_leaves()
            weekly_samples = await uow.dashboard.list_weekly_attendance(week_start, today)

        no_login, no_logout = classify_attendance_exceptions(team_days, now)
        return AdminDashboard(
            no_login=no_login,
            no_logout=no_logout,
            pending_leaves=pending_leaves,
            weekly_hours=total_weekly_minutes(weekly_samples),
            refreshed_at=now,
        )
