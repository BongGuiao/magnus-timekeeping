from datetime import date
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.attendance.domain.entities.admin_dashboard import (
    PendingLeaveSummary,
    TeamAttendanceDay,
    WeeklyAttendanceSample,
)
from app.attendance.domain.entities.attendance_employee import AttendanceEmployee
from app.attendance.infrastructure.db_model import AttendanceModel
from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import LeaveApplicationModel


def _employee_columns(model, prefix: str):
    return [
        model.id.label(f"{prefix}id"),
        model.employee_no.label(f"{prefix}employee_no"),
        model.first_name.label(f"{prefix}first_name"),
        model.middle_name.label(f"{prefix}middle_name"),
        model.last_name.label(f"{prefix}last_name"),
        model.suffix.label(f"{prefix}suffix"),
        model.preferred_name.label(f"{prefix}preferred_name"),
    ]


def _employee_from(row, prefix: str) -> AttendanceEmployee:
    values = row._mapping
    return AttendanceEmployee(
        id=values[f"{prefix}id"],
        employee_no=values[f"{prefix}employee_no"],
        first_name=values[f"{prefix}first_name"],
        middle_name=values[f"{prefix}middle_name"],
        last_name=values[f"{prefix}last_name"],
        suffix=values[f"{prefix}suffix"],
        preferred_name=values[f"{prefix}preferred_name"],
    )


class SqlAlchemyAdminDashboardRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_team_attendance(
        self, supervisor_employee_id: UUID, today: date, month_start: date
    ) -> list[TeamAttendanceDay]:
        SupervisorModel = aliased(EmployeeModel)
        rows = (
            await self._session.execute(
                select(
                    *_employee_columns(EmployeeModel, "employee_"),
                    *_employee_columns(SupervisorModel, "supervisor_"),
                    AttendanceModel.work_date,
                    AttendanceModel.corrected_clock_in_at,
                    AttendanceModel.clock_in_at,
                    AttendanceModel.corrected_clock_out_at,
                    AttendanceModel.clock_out_at,
                    AttendanceModel.expected_clock_out_at,
                    AttendanceModel.is_absent,
                    AttendanceModel.leave_type,
                )
                .distinct()
                .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                .join(AttendanceModel, AttendanceModel.user_id == UserModel.id)
                .join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                )
                .join(
                    SupervisorModel,
                    SupervisorModel.id == EmploymentAssignmentModel.supervisor_employee_id,
                )
                .where(
                    EmployeeModel.is_active.is_(True),
                    EmployeeModel.record_status == "ACTIVE",
                    UserModel.is_active.is_(True),
                    UserModel.account_status == "ACTIVE",
                    SupervisorModel.is_active.is_(True),
                    SupervisorModel.record_status == "ACTIVE",
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                    EmploymentAssignmentModel.effective_from <= today,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= today,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= today,
                    ),
                    AttendanceModel.record_status == "VALID",
                    AttendanceModel.work_date >= month_start,
                    AttendanceModel.work_date <= today,
                )
                .order_by(AttendanceModel.work_date.desc(), EmployeeModel.employee_no)
            )
        ).all()
        return [
            TeamAttendanceDay(
                employee=_employee_from(row, "employee_"),
                supervisor=_employee_from(row, "supervisor_"),
                work_date=row.work_date,
                clock_in_at=row.corrected_clock_in_at or row.clock_in_at,
                clock_out_at=row.corrected_clock_out_at or row.clock_out_at,
                expected_clock_out_at=row.expected_clock_out_at,
                is_absent=row.is_absent,
                leave_type=row.leave_type,
            )
            for row in rows
        ]

    async def list_pending_leaves(
        self, supervisor_employee_id: UUID | None = None, today: date | None = None
    ) -> list[PendingLeaveSummary]:
        conditions = [
            LeaveApplicationModel.is_active.is_(True),
            LeaveApplicationModel.status == "PENDING",
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
        ]
        if supervisor_employee_id is not None:
            if today is None:
                raise ValueError("A date is required when loading team-scoped leave applications.")
            conditions.append(
                exists(
                    select(EmploymentAssignmentModel.id).where(
                        EmploymentAssignmentModel.employee_id == EmployeeModel.id,
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
                )
            )
        rows = (
            await self._session.execute(
                select(
                    LeaveApplicationModel.id,
                    LeaveApplicationModel.application_no,
                    *_employee_columns(EmployeeModel, "employee_"),
                    LeaveTypeModel.leave_name.label("leave_type"),
                    LeaveApplicationModel.start_at,
                    LeaveApplicationModel.end_at,
                    LeaveApplicationModel.requested_minutes,
                    LeaveApplicationModel.status,
                )
                .join(EmployeeModel, EmployeeModel.id == LeaveApplicationModel.employee_id)
                .join(LeaveTypeModel, LeaveTypeModel.id == LeaveApplicationModel.leave_type_id)
                .where(*conditions)
                .order_by(LeaveApplicationModel.start_at, EmployeeModel.employee_no)
            )
        ).all()
        return [
            PendingLeaveSummary(
                id=row.id,
                application_no=row.application_no,
                employee=_employee_from(row, "employee_"),
                leave_type=row.leave_type,
                start_at=row.start_at,
                end_at=row.end_at,
                requested_minutes=row.requested_minutes,
                status=row.status,
            )
            for row in rows
        ]

    async def list_weekly_attendance(
        self,
        week_start: date,
        today: date,
        supervisor_employee_id: UUID | None = None,
    ) -> list[WeeklyAttendanceSample]:
        conditions = [
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
            UserModel.is_active.is_(True),
            UserModel.account_status == "ACTIVE",
            AttendanceModel.record_status == "VALID",
            AttendanceModel.work_date >= week_start,
            AttendanceModel.work_date <= today,
        ]
        if supervisor_employee_id is not None:
            conditions.append(
                exists(
                    select(EmploymentAssignmentModel.id).where(
                        EmploymentAssignmentModel.employee_id == EmployeeModel.id,
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
                )
            )
        rows = (
            await self._session.execute(
                select(
                    *_employee_columns(EmployeeModel, "employee_"),
                    AttendanceModel.corrected_clock_in_at,
                    AttendanceModel.clock_in_at,
                    AttendanceModel.corrected_clock_out_at,
                    AttendanceModel.clock_out_at,
                    AttendanceModel.punch_metadata,
                )
                .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                .join(AttendanceModel, AttendanceModel.user_id == UserModel.id)
                .where(*conditions)
            )
        ).all()
        return [
            WeeklyAttendanceSample(
                employee=_employee_from(row, "employee_"),
                clock_in_at=row.corrected_clock_in_at or row.clock_in_at,
                clock_out_at=row.corrected_clock_out_at or row.clock_out_at,
                punch_metadata=row.punch_metadata,
            )
            for row in rows
        ]
