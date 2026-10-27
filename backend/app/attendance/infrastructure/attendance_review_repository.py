from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.domain.entities.attendance_review import (
    ReviewableAttendance,
    ReviewableAttendanceRecord,
)
from app.attendance.infrastructure.db_model import AttendanceModel
from app.attendance.infrastructure.entity_mapping import copy_fields, to_attendance_employee
from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.payroll_cutoffs.application.deadline_policy import require_attendance_open


def _supervised_as_of(statement, supervisor_employee_id: UUID, today: date):
    return statement.join(
        EmploymentAssignmentModel,
        EmploymentAssignmentModel.employee_id == EmployeeModel.id,
    ).where(
        EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
        EmploymentAssignmentModel.is_active.is_(True),
        EmploymentAssignmentModel.status == "ACTIVE",
        EmploymentAssignmentModel.effective_from <= today,
        or_(
            EmploymentAssignmentModel.effective_to.is_(None),
            EmploymentAssignmentModel.effective_to >= today,
        ),
        or_(
            EmploymentAssignmentModel.separation_date.is_(None),
            EmploymentAssignmentModel.separation_date >= today,
        ),
    )


def _record(attendance: AttendanceModel, employee: EmployeeModel) -> ReviewableAttendanceRecord:
    return ReviewableAttendanceRecord(
        copy_fields(attendance, ReviewableAttendance), to_attendance_employee(employee)
    )


def _invalid_attendance_statement():
    return (
        select(AttendanceModel, EmployeeModel)
        .join(UserModel, UserModel.id == AttendanceModel.user_id)
        .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
        .where(
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
            UserModel.is_active.is_(True),
            UserModel.account_status == "ACTIVE",
            AttendanceModel.record_status == "INVALID",
        )
    )


class SqlAlchemyAttendanceReviewRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_invalid(
        self, supervisor_employee_id: Optional[UUID], today: date
    ) -> list[ReviewableAttendanceRecord]:
        statement = _invalid_attendance_statement().order_by(
            AttendanceModel.work_date.desc(), EmployeeModel.employee_no
        )
        if supervisor_employee_id is not None:
            statement = _supervised_as_of(statement, supervisor_employee_id, today).distinct()
        rows = (await self._session.execute(statement)).all()
        return [_record(attendance, employee) for attendance, employee in rows]

    async def lock_invalid(
        self, attendance_id: UUID, supervisor_employee_id: Optional[UUID], today: date
    ) -> Optional[ReviewableAttendanceRecord]:
        statement = (
            _invalid_attendance_statement()
            .with_for_update(of=AttendanceModel)
            .where(AttendanceModel.id == attendance_id)
        )
        if supervisor_employee_id is not None:
            statement = _supervised_as_of(statement, supervisor_employee_id, today)
        row = (await self._session.execute(statement)).first()
        return _record(*row) if row is not None else None

    async def save_review(self, attendance: ReviewableAttendance) -> None:
        model = await self._session.get(AttendanceModel, attendance.id)
        model.record_status = attendance.record_status
        model.approved_by_id = attendance.approved_by_id
        model.approved_at = attendance.approved_at
        await self._session.flush()

    async def require_attendance_open(self, employee_id: UUID, work_date: date, now: datetime) -> None:
        await require_attendance_open(self._session, employee_id, work_date, work_date, now)
