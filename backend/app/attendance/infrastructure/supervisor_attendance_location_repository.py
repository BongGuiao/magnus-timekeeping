from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.application.supervisor_attendance_location_ports import (
    SupervisedEmployeeAttendanceQuery,
)
from app.attendance.domain.entities.supervisor_attendance_location import (
    AttendancePunchLocation,
    SupervisedTeamEmployee,
    attendance_punch_locations,
)
from app.attendance.infrastructure.db_model import AttendanceModel
from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel


def _active_team_assignment_conditions(supervisor_employee_id: UUID, current_date: date):
    assignment = EmploymentAssignmentModel.__table__.c
    return (
        assignment.supervisor_employee_id == supervisor_employee_id,
        assignment.is_active.is_(True),
        assignment.status == "ACTIVE",
        assignment.effective_from <= current_date,
        or_(
            assignment.effective_to.is_(None),
            assignment.effective_to >= current_date,
        ),
        or_(
            assignment.separation_date.is_(None),
            assignment.separation_date >= current_date,
        ),
    )


def _employee_name(values: RowMapping) -> str:
    return values["preferred_name"] or " ".join(
        part
        for part in (
            values["first_name"],
            values["middle_name"],
            values["last_name"],
            values["suffix"],
        )
        if part
    )


class SqlAlchemySupervisorAttendanceLocationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_supervised_employees(
        self,
        supervisor_employee_id: UUID,
        current_date: date,
    ) -> list[SupervisedTeamEmployee]:
        assignment = EmploymentAssignmentModel.__table__
        employee = EmployeeModel.__table__
        rows = await self._session.execute(
            select(
                employee.c.id.label("employee_id"),
                employee.c.employee_no.label("employee_code"),
                employee.c.first_name,
                employee.c.middle_name,
                employee.c.last_name,
                employee.c.suffix,
                employee.c.preferred_name,
            )
            .select_from(assignment.join(employee, employee.c.id == assignment.c.employee_id))
            .where(
                employee.c.is_active.is_(True),
                employee.c.record_status == "ACTIVE",
                *_active_team_assignment_conditions(supervisor_employee_id, current_date),
            )
            .distinct()
            .order_by(employee.c.employee_no)
        )
        return [
            SupervisedTeamEmployee(
                employee_id=row["employee_id"],
                employee_code=row["employee_code"],
                employee_name=_employee_name(row),
            )
            for row in rows.mappings()
        ]

    async def list_supervised_employee_companies(
        self,
        supervisor_employee_id: UUID,
        employee_code: str,
        current_date: date,
    ) -> list[UUID]:
        assignment = EmploymentAssignmentModel.__table__
        employee = EmployeeModel.__table__
        rows = await self._session.execute(
            select(assignment.c.company_id)
            .select_from(assignment.join(employee, employee.c.id == assignment.c.employee_id))
            .where(
                employee.c.employee_no == employee_code,
                employee.c.is_active.is_(True),
                employee.c.record_status == "ACTIVE",
                *_active_team_assignment_conditions(supervisor_employee_id, current_date),
            )
            .distinct()
            .order_by(assignment.c.company_id)
        )
        return list(rows.scalars().all())

    async def list_punch_locations(
        self,
        query: SupervisedEmployeeAttendanceQuery,
        current_date: date,
    ) -> list[AttendancePunchLocation]:
        attendance = AttendanceModel.__table__
        user = UserModel.__table__
        employee = EmployeeModel.__table__
        assignment = EmploymentAssignmentModel.__table__
        rows = (
            await self._session.execute(
                select(
                    attendance.c.id.label("attendance_id"),
                    attendance.c.work_date,
                    attendance.c.clock_in_at,
                    attendance.c.clock_out_at,
                    attendance.c.punch_metadata,
                    employee.c.employee_no.label("employee_code"),
                    employee.c.first_name,
                    employee.c.middle_name,
                    employee.c.last_name,
                    employee.c.suffix,
                    employee.c.preferred_name,
                )
                .select_from(
                    attendance.join(user, user.c.id == attendance.c.user_id)
                    .join(employee, employee.c.id == user.c.employee_id)
                    .join(assignment, assignment.c.employee_id == employee.c.id)
                )
                .where(
                    employee.c.employee_no == query.employee_code,
                    employee.c.is_active.is_(True),
                    employee.c.record_status == "ACTIVE",
                    user.c.is_active.is_(True),
                    user.c.account_status == "ACTIVE",
                    attendance.c.work_date == query.work_date,
                    assignment.c.company_id == query.company_id,
                    *_active_team_assignment_conditions(query.supervisor_employee_id, current_date),
                )
                .distinct()
            )
        ).all()

        locations: list[AttendancePunchLocation] = []
        for row in rows:
            values = row._mapping
            locations.extend(
                attendance_punch_locations(
                    attendance_id=values["attendance_id"],
                    employee_code=values["employee_code"],
                    employee_name=_employee_name(values),
                    work_date=values["work_date"],
                    clock_in_at=values["clock_in_at"],
                    clock_out_at=values["clock_out_at"],
                    punch_metadata=values["punch_metadata"],
                )
            )
        return locations
