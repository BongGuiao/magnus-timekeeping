from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from app.attendance.domain.entities.supervisor_attendance_location import (
    AttendancePunchLocation,
    SupervisedTeamEmployee,
)


@dataclass(frozen=True)
class SupervisedEmployeeAttendanceQuery:
    supervisor_employee_id: UUID
    company_id: UUID
    employee_code: str
    work_date: date


class SupervisorAttendanceLocationRepository(Protocol):
    async def list_supervised_employees(
        self,
        supervisor_employee_id: UUID,
        current_date: date,
    ) -> list[SupervisedTeamEmployee]: ...

    async def list_supervised_employee_companies(
        self,
        supervisor_employee_id: UUID,
        employee_code: str,
        current_date: date,
    ) -> list[UUID]: ...

    async def list_punch_locations(
        self,
        query: SupervisedEmployeeAttendanceQuery,
        current_date: date,
    ) -> list[AttendancePunchLocation]: ...


class SupervisorAttendanceLocationUnitOfWork(Protocol):
    team_locations: SupervisorAttendanceLocationRepository

    async def __aenter__(self) -> "SupervisorAttendanceLocationUnitOfWork": ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
