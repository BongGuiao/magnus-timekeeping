from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Iterable
from uuid import UUID

from app.attendance.application.admin_dashboard_ports import AdminDashboardUnitOfWork
from app.attendance.application.clock import ph_today, utc_now
from app.attendance.domain.admin_dashboard_rules import classify_attendance_exceptions
from app.attendance.domain.entities.admin_dashboard import (
    AdminDashboard,
    EmployeeWeeklyHours,
    WeeklyAttendanceSample,
    PunchedEmployeeToday,
)
from app.attendance.domain.worked_minutes import net_worked_minutes
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
    team_scope: bool = False


@dataclass
class GetPunchedEmployeesInput:
    work_date: date
    approver_employee_id: UUID


class GetPunchedEmployeesUseCase(BaseUseCase[list[PunchedEmployeeToday]]):
    def __init__(self, uow: AdminDashboardUnitOfWork):
        self._uow = uow

    async def _execute(self, data: GetPunchedEmployeesInput) -> list[PunchedEmployeeToday]:
        async with self._uow as uow:
            return await uow.dashboard.list_employees_punched_on_day(
                data.work_date,
                approver_employee_id=data.approver_employee_id,
            )


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
            supervisor_employee_id = data.supervisor_employee_id if data.team_scope else None
            pending_leaves = await uow.dashboard.list_pending_leaves(
                supervisor_employee_id=supervisor_employee_id,
                today=today if data.team_scope else None,
            )
            weekly_samples = await uow.dashboard.list_weekly_attendance(
                week_start,
                today,
                supervisor_employee_id=supervisor_employee_id,
            )
            punched_employees_today = await uow.dashboard.list_employees_punched_on_day(
                today,
                approver_employee_id=supervisor_employee_id,
            )

        no_login, no_logout = classify_attendance_exceptions(team_days, now)
        return AdminDashboard(
            no_login=no_login,
            no_logout=no_logout,
            pending_leaves=pending_leaves,
            weekly_hours=total_weekly_minutes(weekly_samples),
            employees_punched_today=len(punched_employees_today),
            punched_employees_today=[] if data.team_scope else punched_employees_today,
            refreshed_at=now,
        )
