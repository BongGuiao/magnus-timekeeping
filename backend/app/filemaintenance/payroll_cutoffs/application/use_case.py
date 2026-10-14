from dataclasses import replace
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, NoReturn
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError

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
    calculate_employee_cutoff_totals,
)
from app.filemaintenance.payroll_cutoffs.domain.entities.payroll_cutoff import PayrollCutoffEntity
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import (
    EmployeeCutoffResultModel,
)
from app.filemaintenance.schedule.infrastructure.db_model import ScheduleTemplateModel

PH_TIMEZONE = ZoneInfo("Asia/Manila")


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
                repo = uow.get_repo(PayrollCutoffEntity, PayrollCutoffModel)
                existing = await repo.find_one(PayrollCutoffModel.id == cutoff_id)
                if existing is None:
                    return None

                merged = {**existing.__dict__, **payload}
                _validate_period(merged["period_start"], merged["period_end"])
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
            select(EmployeeCutoffResultModel, EmployeeModel, PayrollCutoffModel)
            .join(EmployeeModel, EmployeeModel.id == EmployeeCutoffResultModel.employee_id)
            .join(PayrollCutoffModel, PayrollCutoffModel.id == EmployeeCutoffResultModel.cutoff_id)
            .where(EmployeeCutoffResultModel.cutoff_id == cutoff_id)
            .order_by(EmployeeModel.last_name, EmployeeModel.first_name, EmployeeModel.employee_no)
        )
        if employee_id is not None:
            statement = statement.where(EmployeeCutoffResultModel.employee_id == employee_id)
        result = await session.execute(statement)
        entities = []
        for result_model, employee, cutoff in result.all():
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
                select(EmployeeCutoffResultModel, EmployeeModel, PayrollCutoffModel)
                .join(EmployeeModel, EmployeeModel.id == EmployeeCutoffResultModel.employee_id)
                .join(PayrollCutoffModel, PayrollCutoffModel.id == EmployeeCutoffResultModel.cutoff_id)
                .where(EmployeeCutoffResultModel.employee_id == actor_employee_id)
                .order_by(EmployeeCutoffResultModel.calculated_at.desc())
            )
            entities: list[EmployeeCutoffResultEntity] = []
            for result_model, employee, cutoff in result.all():
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
                select(EmployeeCutoffResultModel, EmployeeModel, PayrollCutoffModel)
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
                .order_by(PayrollCutoffModel.period_start.desc(), EmployeeModel.last_name, EmployeeModel.first_name)
            )
            entities = []
            seen_result_ids: set[UUID] = set()
            for result_model, employee, cutoff in result.all():
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
                entities.append(entity)
            return entities

    async def acknowledge(
        self,
        cutoff_id: UUID,
        result_id: UUID,
        actor_id: UUID,
        can_manage_payroll: bool,
    ) -> EmployeeCutoffResultEntity:
        async with self.uow as active_uow:
            session = active_uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            result = await session.scalar(
                select(EmployeeCutoffResultModel)
                .where(
                    EmployeeCutoffResultModel.id == result_id,
                    EmployeeCutoffResultModel.cutoff_id == cutoff_id,
                )
                .with_for_update()
            )
            if result is None:
                raise LookupError("Payroll cutoff result not found.")
            actor_employee_id = await session.scalar(
                select(UserModel.employee_id).where(
                    UserModel.id == actor_id,
                    UserModel.is_active.is_(True),
                )
            )
            if actor_employee_id is not None and actor_employee_id == result.employee_id:
                if result.employee_confirmation_status != "PENDING":
                    raise ValueError("Employee confirmation has already been recorded.")
                result.employee_confirmation_status = "ACKNOWLEDGED"
            else:
                cutoff = await session.scalar(
                    select(PayrollCutoffModel).where(PayrollCutoffModel.id == cutoff_id)
                )
                if cutoff is None:
                    raise LookupError("Payroll cutoff not found.")
                is_assigned_supervisor = None
                if actor_employee_id is not None:
                    is_assigned_supervisor = await session.scalar(
                        select(EmploymentAssignmentModel.employee_id)
                        .where(
                            EmploymentAssignmentModel.employee_id == result.employee_id,
                            EmploymentAssignmentModel.supervisor_employee_id == actor_employee_id,
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
                        .limit(1)
                    )
                if is_assigned_supervisor is not None:
                    if result.employee_confirmation_status != "ACKNOWLEDGED":
                        raise ValueError("The employee must acknowledge the calculation first.")
                    if result.supervisor_status != "PENDING":
                        raise ValueError("Supervisor acknowledgment has already been recorded.")
                    result.supervisor_status = "ACKNOWLEDGED"
                elif can_manage_payroll:
                    if result.supervisor_status != "ACKNOWLEDGED":
                        raise ValueError("The supervisor must acknowledge the calculation first.")
                    if result.hr_status != "PENDING":
                        raise ValueError("HR acknowledgment has already been recorded.")
                    result.hr_status = "ACKNOWLEDGED"
                else:
                    raise PermissionError(
                        "Only the employee, assigned supervisor, or payroll HR can acknowledge this result."
                    )

            await session.flush()
            results = await self._load_results_with_employee_names(session, cutoff_id)
            updated = next((item for item in results if item.id == result_id), None)
            if updated is None:
                raise RuntimeError("Acknowledged payroll cutoff result could not be reloaded.")
            return updated

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
            exception_facts: list[ExceptionFact] = []

            if employee_ids:
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
                        undertime_minutes=record.undertime_minutes,
                    )
                    for record, employee_id, required_minutes in attendance_result.all()
                ]

                leave_result = await session.scalars(
                    select(LeaveApplicationModel).where(
                        LeaveApplicationModel.employee_id.in_(employee_ids),
                        LeaveApplicationModel.status == "APPROVED",
                        LeaveApplicationModel.is_active.is_(True),
                        LeaveApplicationModel.start_at < cutoff_end,
                        LeaveApplicationModel.end_at > cutoff_start,
                    )
                )
                leave_applications = list(leave_result.all())
                if leave_applications:
                    leave_dates_result = await session.scalars(
                        select(LeaveApplicationDateModel).where(
                            LeaveApplicationDateModel.leave_application_id.in_(
                                [application.id for application in leave_applications]
                            )
                        )
                    )
                    dates_by_application: dict[UUID, list[LeaveDayFact]] = defaultdict(list)
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
            )
            calculated_at = datetime.now(timezone.utc)
            await session.execute(
                delete(EmployeeCutoffResultModel).where(EmployeeCutoffResultModel.cutoff_id == cutoff_id)
            )
            models = [
                EmployeeCutoffResultModel(
                    cutoff_id=cutoff_id,
                    employee_id=total.employee_id,
                    scheduled_days=total.scheduled_days,
                    paid_days=total.paid_days,
                    regular_minutes=total.regular_minutes,
                    late_minutes=total.late_minutes,
                    undertime_minutes=total.undertime_minutes,
                    absence_minutes=total.absence_minutes,
                    paid_leave_minutes=total.paid_leave_minutes,
                    unpaid_leave_minutes=total.unpaid_leave_minutes,
                    ordinary_ot_minutes=total.ordinary_ot_minutes,
                    rest_day_minutes=total.rest_day_minutes,
                    rest_day_ot_minutes=total.rest_day_ot_minutes,
                    special_day_minutes=total.special_day_minutes,
                    special_day_ot_minutes=total.special_day_ot_minutes,
                    holiday_minutes=total.holiday_minutes,
                    holiday_ot_minutes=total.holiday_ot_minutes,
                    night_regular_minutes=total.night_regular_minutes,
                    night_ot_minutes=total.night_ot_minutes,
                    official_business_minutes=total.official_business_minutes,
                    exception_count=total.exception_count,
                    employee_confirmation_status="PENDING",
                    supervisor_status="PENDING",
                    hr_status="PENDING",
                    payroll_status="HOLD",
                    calculated_at=calculated_at,
                )
                for total in totals
            ]
            session.add_all(models)
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
