from dataclasses import replace
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, NoReturn
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.attendance.application.use_case import (
    resolve_attendance_day_type,
    resolve_schedule_day,
)
from app.attendance.infrastructure.db_model import (
    AttendanceModel,
    OfficialBusinessRequestModel,
    OvertimeApplicationModel,
    PunchExceptionModel,
)
from app.auth.infrastructure.db_model import UserModel
from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import (
    LeaveApplicationDateModel,
    LeaveApplicationModel,
)
from app.filemaintenance.payroll_cutoffs.domain.entities.employee_cutoff_result import (
    AttendanceFact,
    EmployeeCutoffResultEntity,
    ExceptionFact,
    LeaveDayFact,
    LeaveFact,
    OfficialBusinessFact,
    OvertimeFact,
    ScheduledDayFact,
    calculate_employee_cutoff_totals,
    overlap_minutes,
)
from app.filemaintenance.payroll_cutoffs.domain.entities.payroll_cutoff import PayrollCutoffEntity
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_cutoffs.application.deadline_policy import (
    validate_attendance_deadline,
)
from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import (
    EmployeeCutoffResultModel,
)
from app.filemaintenance.schedule.infrastructure.db_model import (
    EmployeeScheduleAssignmentModel,
    ScheduleTemplateModel,
)
from app.payroll.infrastructure.db_model import GrossPayRunModel

PH_TIMEZONE = ZoneInfo("Asia/Manila")


def _operational_group_for_cutoff_result():
    return (
        select(EmploymentAssignmentModel.operational_group)
        .where(
            EmploymentAssignmentModel.employee_id == EmployeeCutoffResultModel.employee_id,
            EmploymentAssignmentModel.is_active.is_(True),
            EmploymentAssignmentModel.status == "ACTIVE",
            EmploymentAssignmentModel.effective_from <= PayrollCutoffModel.period_end,
            or_(
                EmploymentAssignmentModel.effective_to.is_(None),
                EmploymentAssignmentModel.effective_to >= PayrollCutoffModel.period_start,
            ),
            or_(
                EmploymentAssignmentModel.separation_date.is_(None),
                EmploymentAssignmentModel.separation_date >= PayrollCutoffModel.period_start,
            ),
        )
        .order_by(EmploymentAssignmentModel.effective_from.desc())
        .limit(1)
        .scalar_subquery()
    )


async def _scheduled_days_without_attendance(
    session,
    official_business: list[OfficialBusinessFact],
    attendance: list[AttendanceFact],
    schedule_assignments: list[EmployeeScheduleAssignmentModel],
    period_start: date,
    period_end: date,
) -> list[ScheduledDayFact]:
    """Resolve scheduled shifts with OB or schedule-credited attendance but no punch record."""
    recorded = {(fact.employee_id, fact.work_date) for fact in attendance}
    candidates: set[tuple[UUID, date]] = set()
    for request in official_business:
        # Start a day early so an overnight shift from the previous date is included.
        day = request.start_at.astimezone(PH_TIMEZONE).date() - timedelta(days=1)
        last_day = request.end_at.astimezone(PH_TIMEZONE).date()
        while day <= last_day:
            if period_start <= day <= period_end and (request.employee_id, day) not in recorded:
                candidates.add((request.employee_id, day))
            day += timedelta(days=1)
    employee_ids = {assignment.employee_id for assignment in schedule_assignments}
    for employee_id in employee_ids:
        day = period_start
        while day <= period_end:
            if (
                (employee_id, day) not in recorded
                and _schedule_mode_for_date(schedule_assignments, employee_id, day)
                == "SCHEDULE_CREDITED"
            ):
                candidates.add((employee_id, day))
            day += timedelta(days=1)
    if not candidates:
        return []

    facts: list[ScheduledDayFact] = []
    template_minutes: dict[UUID, int] = {}
    for employee_id, work_date in sorted(candidates, key=lambda item: (str(item[0]), item[1])):
        schedule = await resolve_schedule_day(session, employee_id, work_date)
        if (
            schedule.work_type != "REG"
            or schedule.schedule_template_id is None
            or schedule.expected_clock_in_at is None
            or schedule.expected_clock_out_at is None
        ):
            continue
        if schedule.schedule_template_id not in template_minutes:
            template = await session.get(ScheduleTemplateModel, schedule.schedule_template_id)
            template_minutes[schedule.schedule_template_id] = (
                template.required_minutes if template is not None else 0
            ) or 0
        scheduled_minutes = template_minutes[schedule.schedule_template_id]
        day_type = await resolve_attendance_day_type(session, employee_id, work_date)
        facts.append(
            ScheduledDayFact(
                employee_id=employee_id,
                work_date=work_date,
                expected_clock_in_at=schedule.expected_clock_in_at,
                expected_clock_out_at=schedule.expected_clock_out_at,
                scheduled_minutes=scheduled_minutes,
                work_type=schedule.work_type,
                day_type=day_type,
                schedule_credited=schedule.attendance_mode == "SCHEDULE_CREDITED",
            )
        )
    return facts


def _schedule_mode_for_date(
    assignments: list[EmployeeScheduleAssignmentModel],
    employee_id: UUID,
    work_date: date,
) -> str:
    for assignment in assignments:
        if (
            assignment.employee_id == employee_id
            and assignment.effective_from <= work_date
            and (
                assignment.effective_to is None
                or assignment.effective_to >= work_date
            )
        ):
            return assignment.attendance_mode
    return "PUNCH_REQUIRED"


class PayrollCutoffConflictError(ValueError):
    pass


class PayrollCutoffReferenceError(ValueError):
    pass


def _translate_integrity_error(error: IntegrityError) -> NoReturn:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint_name in (
        "uq_cutoffs_payroll_group_code",
        "cutoffs_payroll_group_id_cutoff_code_key",
    ):
        raise PayrollCutoffConflictError(
            "A cutoff with this code already exists for the payroll group."
        ) from error
    if constraint_name in (
        "cutoffs_payroll_group_id_fkey",
        "cutoffs_locked_by_fkey",
    ):
        raise PayrollCutoffReferenceError(
            "The payroll group or locking user does not exist."
        ) from error
    if constraint_name == "fk_cutoff_export":
        raise PayrollCutoffReferenceError(
            "The export batch does not exist."
        ) from error
    raise error


def _validate_period(start: date, end: date) -> None:
    if end < start:
        raise ValueError("period_end must be on or after period_start.")


def _payroll_undertime_minutes(record: AttendanceModel) -> int:
    break_calculation = (record.punch_metadata or {}).get("break_calculation") or {}
    if (
        isinstance(break_calculation, dict)
        and break_calculation.get("undertime_excludes_break_excess", False)
    ):
        excess = break_calculation.get(
            "excess_minutes_break",
            break_calculation.get("excess_undertime_minutes", 0),
        )
        return record.undertime_minutes + int(excess or 0)
    return record.undertime_minutes


class CreatePayrollCutoffUseCase(BaseUseCase[PayrollCutoffEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> PayrollCutoffEntity:
        _validate_period(payload["period_start"], payload["period_end"])
        try:
            async with self.uow as uow:
                repo = uow.get_repo(PayrollCutoffEntity, PayrollCutoffModel)
                return await repo.add(payload)
        except IntegrityError as error:
            _translate_integrity_error(error)


class GetPayrollCutoffUseCase(BaseUseCase[PayrollCutoffEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, cutoff_id: UUID) -> PayrollCutoffEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(PayrollCutoffEntity, PayrollCutoffModel)
            return await repo.find_one(PayrollCutoffModel.id == cutoff_id)


class ListPayrollCutoffsUseCase(BaseUseCase[list[PayrollCutoffEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        payroll_group_id: UUID | None = None,
        cutoff_status: str | None = None,
        is_active: bool | None = None,
        period_start_from: date | None = None,
        period_start_to: date | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PayrollCutoffEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(PayrollCutoffEntity, PayrollCutoffModel)
            criteria = []
            if payroll_group_id is not None:
                criteria.append(PayrollCutoffModel.payroll_group_id == payroll_group_id)
            if cutoff_status is not None:
                criteria.append(PayrollCutoffModel.status == cutoff_status)
            if is_active is not None:
                criteria.append(PayrollCutoffModel.is_active.is_(is_active))
            if period_start_from is not None:
                criteria.append(PayrollCutoffModel.period_start >= period_start_from)
            if period_start_to is not None:
                criteria.append(PayrollCutoffModel.period_start <= period_start_to)
            return await repo.find_all(
                *criteria,
                order_by=(PayrollCutoffModel.period_start.desc(), PayrollCutoffModel.cutoff_code),
                offset=offset,
                limit=limit,
            )


class UpdatePayrollCutoffUseCase(BaseUseCase[PayrollCutoffEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        cutoff_id: UUID,
        payload: dict[str, Any],
    ) -> PayrollCutoffEntity | None:
        try:
            async with self.uow as uow:
                session = uow.session
                if session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                await session.scalar(
                    select(PayrollCutoffModel.id)
                    .where(PayrollCutoffModel.id == cutoff_id)
                    .with_for_update()
                )
                repo = uow.get_repo(PayrollCutoffEntity, PayrollCutoffModel)
                existing = await repo.find_one(PayrollCutoffModel.id == cutoff_id)
                if existing is None:
                    return None
                if existing.locked_at is not None or existing.status.upper() == "LOCKED":
                    raise ValueError(
                        "A finalized payroll cutoff must be unlocked by an administrator before it can be changed."
                    )
                if existing.attendance_finalized_at is not None:
                    raise ValueError(
                        "A cutoff with finalized attendance cannot be changed."
                    )

                merged = {**existing.__dict__, **payload}
                _validate_period(merged["period_start"], merged["period_end"])
                validate_attendance_deadline(merged["period_end"], merged.get("attendance_deadline"))
                entity = GenericMapper.to_entity(merged, PayrollCutoffEntity)
                changes = {
                    key: value
                    for key, value in entity.__dict__.items()
                    if key not in (
                        "id",
                        "created_at",
                        "created_by",
                        "row_version",
                        "updated_at",
                        "updated_by",
                    )
                }
                updated = replace(
                    existing,
                    **changes,
                    updated_at=entity.updated_at or existing.updated_at,
                    updated_by=entity.updated_by or existing.updated_by,
                    row_version=(existing.row_version or 0) + 1,
                )
                return await repo.update(updated)
        except IntegrityError as error:
            _translate_integrity_error(error)


class CalculateEmployeeCutoffResultsUseCase:
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _load_results_with_employee_names(
        self,
        session: Any,
        cutoff_id: UUID,
        employee_id: UUID | None = None,
    ) -> list[EmployeeCutoffResultEntity]:
        statement = (
            select(
                EmployeeCutoffResultModel,
                EmployeeModel,
                PayrollCutoffModel,
                _operational_group_for_cutoff_result(),
                PayrollCutoffModel.attendance_finalized_at,
                PayrollCutoffModel.locked_at,
            )
            .join(EmployeeModel, EmployeeModel.id == EmployeeCutoffResultModel.employee_id)
            .join(PayrollCutoffModel, PayrollCutoffModel.id == EmployeeCutoffResultModel.cutoff_id)
            .where(EmployeeCutoffResultModel.cutoff_id == cutoff_id)
            .order_by(EmployeeModel.last_name, EmployeeModel.first_name, EmployeeModel.employee_no)
        )
        if employee_id is not None:
            statement = statement.where(EmployeeCutoffResultModel.employee_id == employee_id)
        result = await session.execute(statement)
        entities = []
        for result_model, employee, cutoff, operational_group, finalized_at, locked_at in result.all():
            entity = GenericMapper.to_entity(result_model, EmployeeCutoffResultEntity)
            entity.employee_name = employee.preferred_name or " ".join(
                part
                for part in (
                    employee.first_name,
                    employee.middle_name,
                    employee.last_name,
                    employee.suffix,
                )
                if part
            )
            entity.cutoff_code = cutoff.cutoff_code
            entity.period_start = cutoff.period_start
            entity.period_end = cutoff.period_end
            entity.operational_group = operational_group
            entity.attendance_finalized_at = finalized_at
            entity.cutoff_locked_at = locked_at
            entities.append(entity)
        return entities

    async def list_my_results(self, actor_id: UUID) -> list[EmployeeCutoffResultEntity]:
        async with self.uow as active_uow:
            session = active_uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            actor_employee_id = await session.scalar(
                select(UserModel.employee_id).where(
                    UserModel.id == actor_id,
                    UserModel.is_active.is_(True),
                )
            )
            if actor_employee_id is None:
                raise LookupError("No employee is linked to the signed-in account.")
            result = await session.execute(
                select(
                    EmployeeCutoffResultModel,
                    EmployeeModel,
                    PayrollCutoffModel,
                    _operational_group_for_cutoff_result(),
                    PayrollCutoffModel.attendance_finalized_at,
                    PayrollCutoffModel.locked_at,
                )
                .join(EmployeeModel, EmployeeModel.id == EmployeeCutoffResultModel.employee_id)
                .join(PayrollCutoffModel, PayrollCutoffModel.id == EmployeeCutoffResultModel.cutoff_id)
                .where(EmployeeCutoffResultModel.employee_id == actor_employee_id)
                .order_by(EmployeeCutoffResultModel.calculated_at.desc())
            )
            entities: list[EmployeeCutoffResultEntity] = []
            for result_model, employee, cutoff, operational_group, finalized_at, locked_at in result.all():
                entity = GenericMapper.to_entity(result_model, EmployeeCutoffResultEntity)
                entity.employee_name = employee.preferred_name or " ".join(
                    part
                    for part in (
                        employee.first_name,
                        employee.middle_name,
                        employee.last_name,
                        employee.suffix,
                    )
                    if part
                )
                entity.cutoff_code = cutoff.cutoff_code
                entity.period_start = cutoff.period_start
                entity.period_end = cutoff.period_end
                entity.operational_group = operational_group
                entity.attendance_finalized_at = finalized_at
                entity.cutoff_locked_at = locked_at
                entities.append(entity)
            return entities

    async def list_team_results(self, actor_id: UUID) -> list[EmployeeCutoffResultEntity]:
        async with self.uow as active_uow:
            session = active_uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            actor_employee_id = await session.scalar(
                select(UserModel.employee_id).where(
                    UserModel.id == actor_id,
                    UserModel.is_active.is_(True),
                )
            )
            if actor_employee_id is None:
                raise LookupError("No employee is linked to the signed-in account.")
            result = await session.execute(
                select(
                    EmployeeCutoffResultModel,
                    EmployeeModel,
                    PayrollCutoffModel,
                    EmploymentAssignmentModel.operational_group,
                    PayrollCutoffModel.attendance_finalized_at,
                    PayrollCutoffModel.locked_at,
                )
                .join(EmployeeModel, EmployeeModel.id == EmployeeCutoffResultModel.employee_id)
                .join(PayrollCutoffModel, PayrollCutoffModel.id == EmployeeCutoffResultModel.cutoff_id)
                .join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.employee_id == EmployeeCutoffResultModel.employee_id,
                )
                .where(
                    EmploymentAssignmentModel.supervisor_employee_id == actor_employee_id,
                    EmploymentAssignmentModel.payroll_group_id == PayrollCutoffModel.payroll_group_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.effective_from <= PayrollCutoffModel.period_end,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= PayrollCutoffModel.period_start,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= PayrollCutoffModel.period_start,
                    ),
                )
                .order_by(
                    PayrollCutoffModel.period_start.desc(),
                    EmployeeModel.last_name,
                    EmployeeModel.first_name,
                    EmploymentAssignmentModel.effective_from.desc(),
                )
            )
            entities = []
            seen_result_ids: set[UUID] = set()
            for result_model, employee, cutoff, operational_group, finalized_at, locked_at in result.all():
                if result_model.id in seen_result_ids:
                    continue
                seen_result_ids.add(result_model.id)
                entity = GenericMapper.to_entity(result_model, EmployeeCutoffResultEntity)
                entity.employee_name = employee.preferred_name or " ".join(
                    part
                    for part in (
                        employee.first_name,
                        employee.middle_name,
                        employee.last_name,
                        employee.suffix,
                    )
                    if part
                )
                entity.cutoff_code = cutoff.cutoff_code
                entity.period_start = cutoff.period_start
                entity.period_end = cutoff.period_end
                entity.operational_group = operational_group
                entity.attendance_finalized_at = finalized_at
                entity.cutoff_locked_at = locked_at
                entities.append(entity)
            return entities

    async def list_organization_results(self) -> list[EmployeeCutoffResultEntity]:
        async with self.uow as active_uow:
            session = active_uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            result = await session.execute(
                select(
                    EmployeeCutoffResultModel,
                    EmployeeModel,
                    PayrollCutoffModel,
                    _operational_group_for_cutoff_result(),
                    PayrollCutoffModel.attendance_finalized_at,
                    PayrollCutoffModel.locked_at,
                )
                .join(EmployeeModel, EmployeeModel.id == EmployeeCutoffResultModel.employee_id)
                .join(PayrollCutoffModel, PayrollCutoffModel.id == EmployeeCutoffResultModel.cutoff_id)
                .order_by(
                    PayrollCutoffModel.period_start.desc(),
                    EmployeeModel.last_name,
                    EmployeeModel.first_name,
                )
            )
            entities: list[EmployeeCutoffResultEntity] = []
            for result_model, employee, cutoff, operational_group, finalized_at, locked_at in result.all():
                entity = GenericMapper.to_entity(result_model, EmployeeCutoffResultEntity)
                entity.employee_name = employee.preferred_name or " ".join(
                    part
                    for part in (
                        employee.first_name,
                        employee.middle_name,
                        employee.last_name,
                        employee.suffix,
                    )
                    if part
                )
                entity.cutoff_code = cutoff.cutoff_code
                entity.period_start = cutoff.period_start
                entity.period_end = cutoff.period_end
                entity.operational_group = operational_group
                entity.attendance_finalized_at = finalized_at
                entity.cutoff_locked_at = locked_at
                entities.append(entity)
            return entities

    async def calculate(
        self,
        cutoff_id: UUID,
        actor_id: UUID,
    ) -> list[EmployeeCutoffResultEntity]:
        async with self.uow as active_uow:
            session = active_uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")

            cutoff_result = await session.execute(
                select(PayrollCutoffModel)
                .where(PayrollCutoffModel.id == cutoff_id, PayrollCutoffModel.is_active.is_(True))
                .with_for_update()
            )
            cutoff = cutoff_result.scalar_one_or_none()
            if cutoff is None:
                raise LookupError("Payroll cutoff not found.")
            if cutoff.locked_at is not None or cutoff.status.upper() == "LOCKED":
                raise ValueError("A locked payroll cutoff cannot be recalculated.")
            if cutoff.attendance_finalized_at is not None:
                raise ValueError("Attendance has been finalized and cannot be recalculated.")

            cutoff_start = datetime.combine(cutoff.period_start, time.min, tzinfo=PH_TIMEZONE)
            cutoff_end = datetime.combine(
                cutoff.period_end + timedelta(days=1),
                time.min,
                tzinfo=PH_TIMEZONE,
            )
            employee_result = await session.scalars(
                select(EmploymentAssignmentModel.employee_id)
                .where(
                    EmploymentAssignmentModel.payroll_group_id == cutoff.payroll_group_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.effective_from <= cutoff.period_end,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= cutoff.period_start,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= cutoff.period_start,
                    ),
                )
                .distinct()
            )
            employee_ids = list(employee_result.all())
            attendance_facts: list[AttendanceFact] = []
            leave_facts: list[LeaveFact] = []
            overtime_facts: list[OvertimeFact] = []
            official_business_facts: list[OfficialBusinessFact] = []
            scheduled_day_facts: list[ScheduledDayFact] = []
            exception_facts: list[ExceptionFact] = []
            schedule_assignment_rows: list[EmployeeScheduleAssignmentModel] = []

            if employee_ids:
                schedule_assignment_rows = list(
                    (
                        await session.scalars(
                            select(EmployeeScheduleAssignmentModel)
                            .where(
                                EmployeeScheduleAssignmentModel.employee_id.in_(employee_ids),
                                EmployeeScheduleAssignmentModel.is_active.is_(True),
                                EmployeeScheduleAssignmentModel.status == "APPROVED",
                                EmployeeScheduleAssignmentModel.effective_from
                                <= cutoff.period_end,
                                or_(
                                    EmployeeScheduleAssignmentModel.effective_to.is_(None),
                                    EmployeeScheduleAssignmentModel.effective_to
                                    >= cutoff.period_start,
                                ),
                            )
                            .order_by(
                                EmployeeScheduleAssignmentModel.employee_id,
                                EmployeeScheduleAssignmentModel.effective_from.desc(),
                                EmployeeScheduleAssignmentModel.created_at.desc(),
                            )
                        )
                    ).all()
                )
                attendance_result = await session.execute(
                    select(
                        AttendanceModel,
                        UserModel.employee_id,
                        ScheduleTemplateModel.required_minutes,
                    )
                    .join(UserModel, UserModel.id == AttendanceModel.user_id)
                    .outerjoin(
                        ScheduleTemplateModel,
                        ScheduleTemplateModel.id == AttendanceModel.schedule_template_id,
                    )
                    .where(
                        UserModel.employee_id.in_(employee_ids),
                        AttendanceModel.work_date >= cutoff.period_start,
                        AttendanceModel.work_date <= cutoff.period_end,
                        AttendanceModel.record_status == "VALID",
                    )
                )
                attendance_facts = [
                    AttendanceFact(
                        employee_id=employee_id,
                        work_date=record.work_date,
                        is_absent=record.is_absent,
                        approved_hours_worked=record.approved_hours_worked,
                        approved_night_diff=record.approved_night_diff,
                        scheduled_minutes=required_minutes or 0,
                        work_type=record.work_type,
                        day_type=record.day_type,
                        late_minutes=record.late_minutes,
                        undertime_minutes=_payroll_undertime_minutes(record),
                        expected_clock_in_at=record.expected_clock_in_at,
                        expected_clock_out_at=record.expected_clock_out_at,
                        clock_in_at=record.corrected_clock_in_at or record.clock_in_at,
                        clock_out_at=record.corrected_clock_out_at or record.clock_out_at,
                        schedule_credited=(
                            _schedule_mode_for_date(
                                schedule_assignment_rows,
                                employee_id,
                                record.work_date,
                            )
                            == "SCHEDULE_CREDITED"
                        ),
                    )
                    for record, employee_id, required_minutes in attendance_result.all()
                ]

                leave_statement = select(LeaveApplicationModel).where(
                    LeaveApplicationModel.employee_id.in_(employee_ids),
                    LeaveApplicationModel.status == "APPROVED",
                    LeaveApplicationModel.is_active.is_(True),
                    LeaveApplicationModel.start_at < cutoff_end,
                    LeaveApplicationModel.end_at > cutoff_start,
                )
                if cutoff.attendance_deadline is not None:
                    leave_statement = leave_statement.where(
                        LeaveApplicationModel.approved_at <= cutoff.attendance_deadline
                    )
                leave_result = await session.scalars(leave_statement)
                leave_applications = list(leave_result.all())
                previous_cutoff = await session.scalar(
                    select(PayrollCutoffModel)
                    .where(
                        PayrollCutoffModel.payroll_group_id == cutoff.payroll_group_id,
                        PayrollCutoffModel.period_end < cutoff.period_start,
                        PayrollCutoffModel.is_active.is_(True),
                    )
                    .order_by(PayrollCutoffModel.period_end.desc())
                    .limit(1)
                )
                late_leave_applications: list[LeaveApplicationModel] = []
                previous_cutoff_start: datetime | None = None
                previous_cutoff_end: datetime | None = None
                if (
                    previous_cutoff is not None
                    and previous_cutoff.attendance_deadline is not None
                ):
                    previous_cutoff_start = datetime.combine(
                        previous_cutoff.period_start,
                        time.min,
                        tzinfo=PH_TIMEZONE,
                    )
                    previous_cutoff_end = datetime.combine(
                        previous_cutoff.period_end + timedelta(days=1),
                        time.min,
                        tzinfo=PH_TIMEZONE,
                    )
                    late_leave_result = await session.scalars(
                        select(LeaveApplicationModel).where(
                            LeaveApplicationModel.employee_id.in_(employee_ids),
                            LeaveApplicationModel.status == "APPROVED",
                            LeaveApplicationModel.is_active.is_(True),
                            LeaveApplicationModel.approved_at
                            > previous_cutoff.attendance_deadline,
                            LeaveApplicationModel.start_at < previous_cutoff_end,
                            LeaveApplicationModel.end_at > previous_cutoff_start,
                        )
                    )
                    late_leave_applications = list(late_leave_result.all())

                all_leave_applications = {
                    application.id: application
                    for application in (*leave_applications, *late_leave_applications)
                }
                dates_by_application: dict[UUID, list[LeaveDayFact]] = defaultdict(list)
                if all_leave_applications:
                    leave_dates_result = await session.scalars(
                        select(LeaveApplicationDateModel).where(
                            LeaveApplicationDateModel.leave_application_id.in_(
                                list(all_leave_applications)
                            )
                        )
                    )
                    for leave_date in leave_dates_result.all():
                        dates_by_application[leave_date.leave_application_id].append(
                            LeaveDayFact(
                                leave_date=leave_date.leave_date,
                                paid_minutes=leave_date.approved_paid_minutes,
                                unpaid_minutes=leave_date.approved_unpaid_minutes,
                            )
                        )
                leave_facts = [
                    LeaveFact(
                        employee_id=application.employee_id,
                        start_at=application.start_at,
                        end_at=application.end_at,
                        paid_minutes=application.paid_minutes or 0,
                        unpaid_minutes=application.unpaid_minutes or 0,
                        days=tuple(dates_by_application[application.id]),
                    )
                    for application in leave_applications
                ]
                if previous_cutoff_start is not None and previous_cutoff_end is not None:
                    for application in late_leave_applications:
                        application_days = dates_by_application[application.id]
                        previous_days = tuple(
                            day
                            for day in application_days
                            if previous_cutoff.period_start
                            <= day.leave_date
                            <= previous_cutoff.period_end
                        )
                        if application_days:
                            if not previous_days:
                                continue
                            if not any(day.paid_minutes > 0 for day in previous_days):
                                continue
                            paid_minutes = application.paid_minutes or 0
                            unpaid_minutes = application.unpaid_minutes or 0
                        else:
                            paid_minutes = overlap_minutes(
                                application.paid_minutes or 0,
                                application.start_at,
                                application.end_at,
                                previous_cutoff_start,
                                previous_cutoff_end,
                            )
                            unpaid_minutes = overlap_minutes(
                                application.unpaid_minutes or 0,
                                application.start_at,
                                application.end_at,
                                previous_cutoff_start,
                                previous_cutoff_end,
                            )
                            if paid_minutes <= 0:
                                continue
                        leave_facts.append(
                            LeaveFact(
                                employee_id=application.employee_id,
                                start_at=max(application.start_at, previous_cutoff_start),
                                end_at=min(application.end_at, previous_cutoff_end),
                                paid_minutes=paid_minutes,
                                unpaid_minutes=unpaid_minutes,
                                days=previous_days,
                                carry_forward=True,
                            )
                        )

                overtime_result = await session.execute(
                    select(
                        OvertimeApplicationModel,
                        AttendanceModel.work_type,
                        AttendanceModel.day_type,
                    )
                    .join(
                        AttendanceModel,
                        AttendanceModel.id == OvertimeApplicationModel.attendance_record_id,
                    )
                    .where(
                        OvertimeApplicationModel.employee_id.in_(employee_ids),
                        OvertimeApplicationModel.attendance_date >= cutoff.period_start,
                        OvertimeApplicationModel.attendance_date <= cutoff.period_end,
                        OvertimeApplicationModel.status == "APPROVED",
                        OvertimeApplicationModel.is_active.is_(True),
                    )
                )
                overtime_facts = [
                    OvertimeFact(
                        employee_id=application.employee_id,
                        attendance_date=application.attendance_date,
                        payable_minutes=application.final_payable_minutes or 0,
                        overtime_type=application.overtime_type,
                        work_type=work_type,
                        day_type=day_type,
                    )
                    for application, work_type, day_type in overtime_result.all()
                ]

                business_result = await session.scalars(
                    select(OfficialBusinessRequestModel).where(
                        OfficialBusinessRequestModel.employee_id.in_(employee_ids),
                        OfficialBusinessRequestModel.status == "APPROVED",
                        OfficialBusinessRequestModel.is_active.is_(True),
                        OfficialBusinessRequestModel.start_at < cutoff_end,
                        OfficialBusinessRequestModel.end_at > cutoff_start,
                    )
                )
                official_business_facts = [
                    OfficialBusinessFact(
                        employee_id=request.employee_id,
                        start_at=request.start_at,
                        end_at=request.end_at,
                        approved_minutes=request.approved_minutes or 0,
                    )
                    for request in business_result.all()
                ]
                scheduled_day_facts = await _scheduled_days_without_attendance(
                    session,
                    official_business_facts,
                    attendance_facts,
                    schedule_assignment_rows,
                    cutoff.period_start,
                    cutoff.period_end,
                )

                exception_result = await session.execute(
                    select(UserModel.employee_id, PunchExceptionModel.id)
                    .join(UserModel, UserModel.id == PunchExceptionModel.requested_user_id)
                    .where(
                        UserModel.employee_id.in_(employee_ids),
                        PunchExceptionModel.attempted_at >= cutoff_start,
                        PunchExceptionModel.attempted_at < cutoff_end,
                    )
                )
                exception_facts = [
                    ExceptionFact(employee_id=employee_id)
                    for employee_id, _ in exception_result.all()
                ]

            totals = calculate_employee_cutoff_totals(
                employee_ids,
                attendance_facts,
                leave_facts,
                overtime_facts,
                official_business_facts,
                exception_facts,
                cutoff.period_start,
                cutoff.period_end,
                scheduled_day_facts,
            )
            calculated_at = datetime.now(timezone.utc)
            existing_results = {
                result.employee_id: result
                for result in (
                    await session.scalars(
                        select(EmployeeCutoffResultModel)
                        .where(EmployeeCutoffResultModel.cutoff_id == cutoff_id)
                        .with_for_update()
                    )
                ).all()
            }
            await session.execute(
                update(GrossPayRunModel)
                .where(
                    GrossPayRunModel.cutoff_id == cutoff_id,
                    GrossPayRunModel.is_current.is_(True),
                )
                .values(is_current=False)
            )
            for total in totals:
                result = existing_results.get(total.employee_id)
                if result is None:
                    result = EmployeeCutoffResultModel(
                        cutoff_id=cutoff_id,
                        employee_id=total.employee_id,
                    )
                    session.add(result)
                result.scheduled_days = total.scheduled_days
                result.paid_days = total.paid_days
                result.required_work_minutes = total.required_work_minutes
                result.regular_minutes = total.regular_minutes
                result.late_minutes = total.late_minutes
                result.undertime_minutes = total.undertime_minutes
                result.absence_minutes = total.absence_minutes
                result.paid_leave_minutes = total.paid_leave_minutes
                result.unpaid_leave_minutes = total.unpaid_leave_minutes
                result.ordinary_ot_minutes = total.ordinary_ot_minutes
                result.rest_day_minutes = total.rest_day_minutes
                result.rest_day_ot_minutes = total.rest_day_ot_minutes
                result.special_day_minutes = total.special_day_minutes
                result.special_day_ot_minutes = total.special_day_ot_minutes
                result.holiday_minutes = total.holiday_minutes
                result.holiday_ot_minutes = total.holiday_ot_minutes
                result.night_regular_minutes = total.night_regular_minutes
                result.night_ot_minutes = total.night_ot_minutes
                result.official_business_minutes = total.official_business_minutes
                result.exception_count = total.exception_count
                result.incomplete_time_source_count = total.incomplete_time_source_count
                result.employee_confirmation_status = "PENDING"
                result.supervisor_status = "PENDING"
                result.hr_status = "PENDING"
                result.payroll_status = "HOLD"
                result.calculated_at = calculated_at
            cutoff.calculation_version = "TIME_TOTALS_V1"
            cutoff.updated_at = calculated_at
            cutoff.updated_by = actor_id
            cutoff.row_version += 1
            await session.flush()
            return await self._load_results_with_employee_names(session, cutoff_id)

    async def list(self, cutoff_id: UUID) -> list[EmployeeCutoffResultEntity]:
        async with self.uow as active_uow:
            session = active_uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            cutoff = await session.scalar(
                select(PayrollCutoffModel.id).where(
                    PayrollCutoffModel.id == cutoff_id,
                    PayrollCutoffModel.is_active.is_(True),
                )
            )
            if cutoff is None:
                raise LookupError("Payroll cutoff not found.")
            return await self._load_results_with_employee_names(session, cutoff_id)
