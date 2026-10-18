from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable
from uuid import UUID

from app.attendance.application.clock import ph_today, utc_now
from app.attendance.application.supervisor_attendance_location_ports import (
    SupervisedEmployeeAttendanceQuery,
    SupervisorAttendanceLocationUnitOfWork,
)
from app.attendance.domain.entities.supervisor_attendance_location import (
    AmbiguousSupervisorCompanyError,
    EmployeeNotInSupervisorTeamError,
    SupervisedTeamEmployee,
    SupervisorAttendanceLocations,
)
from app.core.generics.uc_base import BaseUseCase


@dataclass(frozen=True)
class ListSupervisorAttendanceLocationsInput:
    supervisor_employee_id: UUID
    employee_code: str
    work_date: date


class ListSupervisorAttendanceLocationsUseCase(BaseUseCase[SupervisorAttendanceLocations]):
    def __init__(
        self,
        uow: SupervisorAttendanceLocationUnitOfWork,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._uow = uow
        self._clock = clock

    async def _execute(
        self, data: ListSupervisorAttendanceLocationsInput
    ) -> SupervisorAttendanceLocations:
        current_date = ph_today(self._clock())
        async with self._uow as uow:
            company_ids = await uow.team_locations.list_supervised_employee_companies(
                data.supervisor_employee_id,
                data.employee_code,
                current_date,
            )
            if not company_ids:
                raise EmployeeNotInSupervisorTeamError(
                    "Employee code was not found among your currently assigned direct reports."
                )
            if len(company_ids) != 1:
                raise AmbiguousSupervisorCompanyError(
                    "This employee has multiple active company assignments under your supervision."
                )

            company_id = company_ids[0]
            punches = await uow.team_locations.list_punch_locations(
                SupervisedEmployeeAttendanceQuery(
                    supervisor_employee_id=data.supervisor_employee_id,
                    company_id=company_id,
                    employee_code=data.employee_code,
                    work_date=data.work_date,
                ),
                current_date,
            )

        return SupervisorAttendanceLocations(
            company_id=company_id,
            employee_code=data.employee_code,
            work_date=data.work_date,
            punches=punches,
        )


@dataclass(frozen=True)
class ListSupervisorTeamEmployeesInput:
    supervisor_employee_id: UUID


class ListSupervisorTeamEmployeesUseCase(BaseUseCase[list[SupervisedTeamEmployee]]):
    def __init__(
        self,
        uow: SupervisorAttendanceLocationUnitOfWork,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._uow = uow
        self._clock = clock

    async def _execute(
        self, data: ListSupervisorTeamEmployeesInput
    ) -> list[SupervisedTeamEmployee]:
        async with self._uow as uow:
            return await uow.team_locations.list_supervised_employees(
                data.supervisor_employee_id,
                ph_today(self._clock()),
            )
