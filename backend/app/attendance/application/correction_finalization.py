from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.infrastructure.correction_db_model import AttendanceCorrectionModel
from app.attendance.infrastructure.db_model import AttendanceModel
from app.attendance.infrastructure.attendance_merge_queries import not_merged_source
from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.employees.infrastructure.db_model import EmploymentAssignmentModel
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.schedule.infrastructure.db_model import EmployeeScheduleAssignmentModel


async def require_resolved_punches(session: AsyncSession, cutoff: PayrollCutoffModel) -> None:
    def assignment_conditions(work_date):
        return (
            EmploymentAssignmentModel.payroll_group_id == cutoff.payroll_group_id,
            EmploymentAssignmentModel.is_active.is_(True), EmploymentAssignmentModel.status == "ACTIVE",
            EmploymentAssignmentModel.effective_from <= work_date,
            or_(EmploymentAssignmentModel.effective_to.is_(None), EmploymentAssignmentModel.effective_to >= work_date),
            or_(EmploymentAssignmentModel.separation_date.is_(None), EmploymentAssignmentModel.separation_date >= work_date),
            work_date >= cutoff.period_start, work_date <= cutoff.period_end,
        )

    pending = await session.scalar(
        select(func.count(func.distinct(AttendanceCorrectionModel.id)))
        .join(EmploymentAssignmentModel, EmploymentAssignmentModel.employee_id == AttendanceCorrectionModel.employee_id)
        .where(AttendanceCorrectionModel.status == "PENDING", *assignment_conditions(AttendanceCorrectionModel.work_date))
    )
    if pending:
        raise ValueError(f"Resolve {pending} pending attendance correction request(s) before finalizing this cutoff.")
    clock_in = func.coalesce(AttendanceModel.corrected_clock_in_at, AttendanceModel.clock_in_at)
    clock_out = func.coalesce(AttendanceModel.corrected_clock_out_at, AttendanceModel.clock_out_at)
    schedule_credited = exists(select(EmployeeScheduleAssignmentModel.id).where(
        EmployeeScheduleAssignmentModel.employee_id == UserModel.employee_id,
        EmployeeScheduleAssignmentModel.is_active.is_(True), EmployeeScheduleAssignmentModel.status == "APPROVED",
        EmployeeScheduleAssignmentModel.attendance_mode == "SCHEDULE_CREDITED",
        EmployeeScheduleAssignmentModel.effective_from <= AttendanceModel.work_date,
        or_(EmployeeScheduleAssignmentModel.effective_to.is_(None),
            EmployeeScheduleAssignmentModel.effective_to >= AttendanceModel.work_date),
    ))
    incomplete = await session.scalar(
        select(func.count(func.distinct(AttendanceModel.id)))
        .join(UserModel, UserModel.id == AttendanceModel.user_id)
        .join(EmploymentAssignmentModel, EmploymentAssignmentModel.employee_id == UserModel.employee_id)
        .where(
            *assignment_conditions(AttendanceModel.work_date),
            AttendanceModel.is_absent.is_(False), ~schedule_credited,
            not_merged_source(),
            or_(clock_in.is_(None), clock_out.is_(None)),
        )
    )
    if incomplete:
        raise ValueError(f"Resolve {incomplete} incomplete attendance record(s) before finalizing this cutoff.")
