from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import or_, select

from app.attendance.application.clock import ph_today, utc_now
from app.attendance.application.use_case import (
    PH_TIMEZONE,
    calculate_attendance_metrics,
    calculate_break_policy,
    calculate_net_nonpayable_break_minutes,
    calculate_night_differential_minutes,
    calculate_overtime_breakdown,
)
from app.attendance.infrastructure.db_model import AttendanceModel
from app.auth.infrastructure.db_model import UserModel
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import (
    EmployeeCutoffResultModel,
)
from app.filemaintenance.schedule.domain.schedule_upload_rules import (
    ACTIVE_TEMPLATE_STATUS,
    MAX_REASON_LENGTH,
)
from app.filemaintenance.schedule.infrastructure.db_model import (
    ScheduleSegmentModel,
    ScheduleTemplateModel,
)
from app.filemaintenance.schedule.infrastructure.emergency_schedule_db_model import (
    EmergencyScheduleRequestModel,
)


@dataclass(frozen=True)
class EmergencyScheduleTemplateOption:
    id: UUID
    schedule_code: str
    schedule_name: str
    schedule_type: str


@dataclass(frozen=True)
class EmergencyScheduleRequestView:
    id: UUID
    employee_code: str
    employee_name: str
    schedule_code: str
    schedule_name: str
    work_date: date
    reason: str
    status: str
    requested_at: datetime
    reviewed_at: datetime | None
    review_remarks: str | None


@dataclass(frozen=True)
class EmergencyScheduleTemplatesInput:
    employee_id: UUID
    work_date: date


@dataclass(frozen=True)
class SubmitEmergencyScheduleRequestInput:
    employee_id: UUID
    user_id: UUID
    schedule_template_id: UUID
    work_date: date
    reason: str


@dataclass(frozen=True)
class ListEmergencyScheduleRequestsInput:
    employee_id: UUID


@dataclass(frozen=True)
class ListPendingEmergencyScheduleRequestsInput:
    supervisor_employee_id: UUID


@dataclass(frozen=True)
class ReviewEmergencyScheduleRequestInput:
    request_id: UUID
    supervisor_employee_id: UUID
    reviewer_user_id: UUID
    decision: Literal["APPROVED", "REJECTED"]
    remarks: str | None = None


def _active_employment_conditions(work_date: date):
    return (
        EmploymentAssignmentModel.is_active.is_(True),
        EmploymentAssignmentModel.status == "ACTIVE",
        EmploymentAssignmentModel.effective_from <= work_date,
        or_(
            EmploymentAssignmentModel.effective_to.is_(None),
            EmploymentAssignmentModel.effective_to >= work_date,
        ),
        or_(
            EmploymentAssignmentModel.separation_date.is_(None),
            EmploymentAssignmentModel.separation_date >= work_date,
        ),
    )


def _employee_name(employee: EmployeeModel) -> str:
    return employee.preferred_name or " ".join(
        part
        for part in (employee.first_name, employee.middle_name, employee.last_name, employee.suffix)
        if part
    )


async def _active_employee(uow: GenUnitOfWork, employee_id: UUID) -> EmployeeModel:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    employee = await uow.session.scalar(
        select(EmployeeModel).where(
            EmployeeModel.id == employee_id,
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
        )
    )
    if employee is None:
        raise ValueError("No active employee profile is linked to this account.")
    return employee


async def _company_ids_for_employee(
    uow: GenUnitOfWork, employee_id: UUID, work_date: date
) -> set[UUID]:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    return set(
        (
            await uow.session.scalars(
                select(EmploymentAssignmentModel.company_id)
                .where(
                    EmploymentAssignmentModel.employee_id == employee_id,
                    *_active_employment_conditions(work_date),
                )
                .distinct()
            )
        ).all()
    )


async def _require_current_open_unprocessed_cutoff(
    uow: GenUnitOfWork,
    employee_id: UUID,
    work_date: date,
    today: date,
) -> None:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    payroll_group_ids = set(
        (
            await uow.session.scalars(
                select(EmploymentAssignmentModel.payroll_group_id)
                .where(
                    EmploymentAssignmentModel.employee_id == employee_id,
                    *_active_employment_conditions(work_date),
                    EmploymentAssignmentModel.payroll_group_id.is_not(None),
                )
                .distinct()
            )
        ).all()
    )
    if len(payroll_group_ids) != 1:
        raise ValueError("A single active payroll group is required to file a retroactive emergency schedule request.")

    cutoffs = list(
        (
            await uow.session.scalars(
                select(PayrollCutoffModel).where(
                    PayrollCutoffModel.payroll_group_id.in_(payroll_group_ids),
                    PayrollCutoffModel.is_active.is_(True),
                    PayrollCutoffModel.period_start <= work_date,
                    PayrollCutoffModel.period_end >= work_date,
                    PayrollCutoffModel.period_start <= today,
                    PayrollCutoffModel.period_end >= today,
                )
                .with_for_update()
            )
        ).all()
    )
    if len(cutoffs) != 1:
        raise ValueError("The work date must fall within the employee's current open payroll cutoff.")
    cutoff = cutoffs[0]
    if cutoff.locked_at is not None or cutoff.status.upper() == "LOCKED":
        raise ValueError("Retroactive emergency schedule requests are not allowed after the payroll cutoff is locked.")

    cutoff_result_id = await uow.session.scalar(
        select(EmployeeCutoffResultModel.id).where(
            EmployeeCutoffResultModel.cutoff_id == cutoff.id,
        ).limit(1)
    )
    if cutoff_result_id is not None:
        raise ValueError("The current payroll cutoff has already been processed.")


async def _validate_retroactive_work_date(
    uow: GenUnitOfWork,
    employee_id: UUID,
    work_date: date,
) -> bool:
    today = ph_today(utc_now())
    if work_date >= today:
        return False
    if work_date < today - timedelta(days=7):
        raise ValueError("Emergency schedule requests can only be filed up to 7 days after the work date.")
    await _require_current_open_unprocessed_cutoff(uow, employee_id, work_date, today)
    return True


async def _require_template(
    uow: GenUnitOfWork,
    employee_id: UUID,
    template_id: UUID,
    work_date: date,
) -> ScheduleTemplateModel:
    company_ids = await _company_ids_for_employee(uow, employee_id, work_date)
    if not company_ids:
        raise ValueError("No active employment assignment covers the requested work date.")
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    template = await uow.session.scalar(
        select(ScheduleTemplateModel).where(
            ScheduleTemplateModel.id == template_id,
            ScheduleTemplateModel.company_id.in_(company_ids),
            ScheduleTemplateModel.is_active.is_(True),
            ScheduleTemplateModel.status == ACTIVE_TEMPLATE_STATUS,
            ScheduleTemplateModel.effective_from <= work_date,
            or_(
                ScheduleTemplateModel.effective_to.is_(None),
                ScheduleTemplateModel.effective_to >= work_date,
            ),
        )
    )
    if template is None:
        raise ValueError("Choose an active schedule template valid for the employee and work date.")
    return template


async def _recalculate_attendance_for_emergency_schedule(
    uow: GenUnitOfWork,
    request: EmergencyScheduleRequestModel,
    template: ScheduleTemplateModel,
    reviewer_user_id: UUID,
) -> None:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    attendance = await uow.session.scalar(
        select(AttendanceModel)
        .where(
            AttendanceModel.user_id == request.requested_by,
            AttendanceModel.work_date == request.work_date,
        )
        .with_for_update()
    )
    if attendance is None:
        raise ValueError("No attendance record exists for this past work date; contact HR to correct the attendance.")
    if attendance.is_locked:
        raise ValueError("This attendance record is locked and cannot be recalculated.")
    if attendance.record_status != "VALID":
        raise ValueError("Only valid attendance records can be recalculated for an emergency schedule.")
    actual_clock_in = attendance.corrected_clock_in_at or attendance.clock_in_at
    actual_clock_out = attendance.corrected_clock_out_at or attendance.clock_out_at
    if actual_clock_in is None or actual_clock_out is None:
        raise ValueError("The attendance record must have completed clock-in and clock-out punches before recalculation.")

    work_segments = list(
        (
            await uow.session.scalars(
                select(ScheduleSegmentModel)
                .where(
                    ScheduleSegmentModel.schedule_template_id == template.id,
                    ScheduleSegmentModel.segment_type == "WORK",
                )
                .order_by(ScheduleSegmentModel.segment_sequence)
            )
        ).all()
    )
    if not work_segments:
        raise ValueError("The selected emergency schedule has no work segments.")
    break_segments = list(
        (
            await uow.session.scalars(
                select(ScheduleSegmentModel)
                .where(
                    ScheduleSegmentModel.schedule_template_id == template.id,
                    ScheduleSegmentModel.break_slot.is_not(None),
                )
                .order_by(ScheduleSegmentModel.segment_sequence)
            )
        ).all()
    )
    first_segment = work_segments[0]
    last_segment = work_segments[-1]
    expected_start = datetime.combine(
        request.work_date, first_segment.start_time, tzinfo=PH_TIMEZONE
    )
    expected_end = datetime.combine(
        request.work_date + timedelta(days=last_segment.end_day_offset),
        last_segment.end_time,
        tzinfo=PH_TIMEZONE,
    )
    if expected_end <= expected_start:
        raise ValueError("The selected emergency schedule has invalid work segment times.")

    previous_schedule_template_id = attendance.schedule_template_id
    schedule_context = dict((attendance.punch_metadata or {}).get("schedule_context") or {})
    schedule_context.update(
        {
            "schedule_template_id": str(template.id),
            "emergency_schedule_request_id": str(request.id),
            "grace_minutes": template.grace_minutes,
            "ot_eligible": template.ot_eligible,
            "minimum_ot_minutes": template.minimum_ot_minutes,
            "pre_shift_ot_allowed": template.pre_shift_ot_allowed,
            "early_clock_in_allowance_minutes": first_segment.flex_start_minutes,
            "break_rules": [
                {
                    "segment_id": str(segment.id),
                    "break_slot": segment.break_slot,
                    "segment_type": segment.segment_type,
                    "break_minutes": segment.break_minutes,
                    "auto_deduct": segment.auto_deduct,
                    "start_at": datetime.combine(
                        request.work_date, segment.start_time, tzinfo=PH_TIMEZONE
                    ).isoformat(),
                    "end_at": datetime.combine(
                        request.work_date + timedelta(days=segment.end_day_offset),
                        segment.end_time,
                        tzinfo=PH_TIMEZONE,
                    ).isoformat(),
                }
                for segment in break_segments
            ],
        }
    )
    metadata = dict(attendance.punch_metadata or {})
    metadata["schedule_context"] = schedule_context
    attendance.schedule_template_id = template.id
    attendance.expected_clock_in_at = expected_start
    attendance.expected_clock_out_at = expected_end
    attendance.work_type = "REG"
    attendance.updated_by = reviewer_user_id

    break_rules = schedule_context["break_rules"]
    break_excess_minutes, unpaid_break_minutes, break_intervals = calculate_break_policy(
        attendance, break_rules
    )
    regular_ot, night_ot, total_ot = calculate_overtime_breakdown(
        expected_clock_in_at=expected_start,
        expected_clock_out_at=expected_end,
        actual_clock_in_at=actual_clock_in,
        actual_clock_out_at=actual_clock_out,
        ot_eligible=template.ot_eligible,
        minimum_ot_minutes=template.minimum_ot_minutes,
        pre_shift_ot_allowed=template.pre_shift_ot_allowed,
        break_intervals=break_intervals,
    )
    late_minutes, undertime_minutes, _ = calculate_attendance_metrics(
        expected_clock_in_at=expected_start,
        expected_clock_out_at=expected_end,
        actual_clock_in_at=actual_clock_in,
        actual_clock_out_at=actual_clock_out,
        grace_minutes=template.grace_minutes,
        ot_eligible=template.ot_eligible,
        minimum_ot_minutes=template.minimum_ot_minutes,
        pre_shift_ot_allowed=template.pre_shift_ot_allowed,
        break_intervals=break_intervals,
    )
    night_minutes = calculate_night_differential_minutes(
        actual_clock_in_at=actual_clock_in,
        actual_clock_out_at=actual_clock_out,
        break_intervals=break_intervals,
    )
    attendance.late_minutes = late_minutes
    attendance.undertime_minutes = undertime_minutes
    attendance.calculated_ot_minutes = total_ot
    attendance.overtime_hours = Decimal(total_ot) / Decimal(60)
    attendance.regular_overtime_minutes = regular_ot
    attendance.regular_overtime_hours = Decimal(regular_ot) / Decimal(60)
    attendance.night_differential_overtime_minutes = night_ot
    attendance.night_differential_overtime_hours = Decimal(night_ot) / Decimal(60)
    attendance.night_differential_minutes = night_minutes
    attendance.night_differential_hours = Decimal(night_minutes) / Decimal(60)
    attendance.approved_night_differential_minutes = night_minutes
    attendance.approved_night_diff = night_minutes / 60
    metadata["break_calculation"] = {
        "excess_undertime_minutes": break_excess_minutes,
        "excess_minutes_break": break_excess_minutes,
        "unpaid_break_minutes": unpaid_break_minutes,
        "net_nonpayable_minutes": calculate_net_nonpayable_break_minutes(
            attendance,
            break_rules,
            break_intervals,
            actual_clock_in,
            actual_clock_out,
        ),
        "undertime_excludes_break_excess": True,
    }
    metadata["emergency_schedule_recalculation"] = {
        "request_id": str(request.id),
        "reviewed_by": str(reviewer_user_id),
        "recalculated_at": utc_now().isoformat(),
        "previous_schedule_template_id": (
            str(previous_schedule_template_id) if previous_schedule_template_id else None
        ),
    }
    attendance.punch_metadata = metadata


def _request_view(row) -> EmergencyScheduleRequestView:
    request, employee, template = row
    return EmergencyScheduleRequestView(
        id=request.id,
        employee_code=employee.employee_no,
        employee_name=_employee_name(employee),
        schedule_code=template.schedule_code,
        schedule_name=template.schedule_name,
        work_date=request.work_date,
        reason=request.reason,
        status=request.status,
        requested_at=request.requested_at,
        reviewed_at=request.reviewed_at,
        review_remarks=request.review_remarks,
    )


def _request_query():
    return (
        select(EmergencyScheduleRequestModel, EmployeeModel, ScheduleTemplateModel)
        .join(EmployeeModel, EmployeeModel.id == EmergencyScheduleRequestModel.employee_id)
        .join(
            ScheduleTemplateModel,
            ScheduleTemplateModel.id == EmergencyScheduleRequestModel.schedule_template_id,
        )
    )


class ListEmergencyScheduleTemplatesUseCase(
    BaseUseCase[list[EmergencyScheduleTemplateOption]]
):
    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow

    async def _execute(
        self, data: EmergencyScheduleTemplatesInput
    ) -> list[EmergencyScheduleTemplateOption]:
        async with self._uow as uow:
            await _active_employee(uow, data.employee_id)
            await _validate_retroactive_work_date(
                uow, data.employee_id, data.work_date
            )
            company_ids = await _company_ids_for_employee(uow, data.employee_id, data.work_date)
            if not company_ids:
                raise ValueError("No active employment assignment covers the requested work date.")
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            templates = (
                await uow.session.scalars(
                    select(ScheduleTemplateModel)
                    .where(
                        ScheduleTemplateModel.company_id.in_(company_ids),
                        ScheduleTemplateModel.is_active.is_(True),
                        ScheduleTemplateModel.status == ACTIVE_TEMPLATE_STATUS,
                        ScheduleTemplateModel.effective_from <= data.work_date,
                        or_(
                            ScheduleTemplateModel.effective_to.is_(None),
                            ScheduleTemplateModel.effective_to >= data.work_date,
                        ),
                    )
                    .order_by(ScheduleTemplateModel.schedule_code)
                )
            ).all()
            return [
                EmergencyScheduleTemplateOption(
                    id=template.id,
                    schedule_code=template.schedule_code,
                    schedule_name=template.schedule_name,
                    schedule_type=template.schedule_type,
                )
                for template in templates
            ]


class SubmitEmergencyScheduleRequestUseCase(BaseUseCase[EmergencyScheduleRequestView]):
    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow

    async def _execute(
        self, data: SubmitEmergencyScheduleRequestInput
    ) -> EmergencyScheduleRequestView:
        reason = data.reason.strip()
        if not reason:
            raise ValueError("Provide a reason for the emergency schedule change.")
        if len(reason) > MAX_REASON_LENGTH:
            raise ValueError(f"reason must be at most {MAX_REASON_LENGTH} characters.")

        async with self._uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            employee = await _active_employee(uow, data.employee_id)
            account_employee_id = await uow.session.scalar(
                select(UserModel.employee_id).where(UserModel.id == data.user_id)
            )
            if account_employee_id != employee.id:
                raise ValueError("This account is not linked to the requested employee profile.")
            is_retroactive = await _validate_retroactive_work_date(
                uow, data.employee_id, data.work_date
            )
            attendance_id = await uow.session.scalar(
                select(AttendanceModel.id).where(
                    AttendanceModel.user_id == data.user_id,
                    AttendanceModel.work_date == data.work_date,
                )
            )
            if is_retroactive and attendance_id is None:
                raise ValueError("No attendance record exists for this past work date; contact HR to correct the attendance.")
            if not is_retroactive and attendance_id is not None:
                raise ValueError(
                    "Attendance has already started for this date; an emergency schedule must be requested before clock-in."
                )

            await _require_template(
                uow, data.employee_id, data.schedule_template_id, data.work_date
            )
            supervisor_ids = set(
                (
                    await uow.session.scalars(
                        select(EmploymentAssignmentModel.supervisor_employee_id)
                        .where(
                            EmploymentAssignmentModel.employee_id == data.employee_id,
                            *_active_employment_conditions(data.work_date),
                            EmploymentAssignmentModel.supervisor_employee_id.is_not(None),
                        )
                        .distinct()
                    )
                ).all()
            )
            if not supervisor_ids:
                raise ValueError("No supervisor is assigned for the requested work date.")
            if len(supervisor_ids) > 1:
                raise ValueError("More than one supervisor is assigned for the requested work date; contact HR.")
            if employee.id in supervisor_ids:
                raise ValueError("An employee cannot approve their own emergency schedule request.")

            await uow.session.execute(
                select(EmployeeModel.id)
                .where(EmployeeModel.id == employee.id)
                .with_for_update()
            )
            existing = await uow.session.scalar(
                select(EmergencyScheduleRequestModel.id).where(
                    EmergencyScheduleRequestModel.employee_id == employee.id,
                    EmergencyScheduleRequestModel.work_date == data.work_date,
                    EmergencyScheduleRequestModel.status.in_(("PENDING_APPROVAL", "APPROVED")),
                )
            )
            if existing is not None:
                raise ValueError("An emergency schedule request is already pending or approved for this date.")

            request = EmergencyScheduleRequestModel(
                employee_id=employee.id,
                requested_by=data.user_id,
                schedule_template_id=data.schedule_template_id,
                work_date=data.work_date,
                reason=reason,
            )
            uow.session.add(request)
            await uow.session.flush()
            result = await uow.session.execute(
                _request_query().where(EmergencyScheduleRequestModel.id == request.id)
            )
            row = result.first()
            if row is None:
                raise RuntimeError("The emergency schedule request could not be reloaded after saving.")
            return _request_view(row)


class ListMyEmergencyScheduleRequestsUseCase(
    BaseUseCase[list[EmergencyScheduleRequestView]]
):
    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow

    async def _execute(
        self, data: ListEmergencyScheduleRequestsInput
    ) -> list[EmergencyScheduleRequestView]:
        async with self._uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            rows = await uow.session.execute(
                _request_query()
                .where(EmergencyScheduleRequestModel.employee_id == data.employee_id)
                .order_by(EmergencyScheduleRequestModel.work_date.desc())
                .limit(100)
            )
            return [_request_view(row) for row in rows.all()]


class ListPendingEmergencyScheduleRequestsUseCase(
    BaseUseCase[list[EmergencyScheduleRequestView]]
):
    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow

    async def _execute(
        self, data: ListPendingEmergencyScheduleRequestsInput
    ) -> list[EmergencyScheduleRequestView]:
        async with self._uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            rows = await uow.session.execute(
                _request_query()
                .join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.employee_id == EmergencyScheduleRequestModel.employee_id,
                )
                .where(
                    EmploymentAssignmentModel.supervisor_employee_id == data.supervisor_employee_id,
                    *_active_employment_conditions(EmergencyScheduleRequestModel.work_date),
                    EmergencyScheduleRequestModel.employee_id != data.supervisor_employee_id,
                    EmergencyScheduleRequestModel.status == "PENDING_APPROVAL",
                )
                .distinct()
                .order_by(EmergencyScheduleRequestModel.work_date)
                .limit(200)
            )
            return [_request_view(row) for row in rows.all()]


class ReviewEmergencyScheduleRequestUseCase(BaseUseCase[EmergencyScheduleRequestView]):
    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow

    async def _execute(
        self, data: ReviewEmergencyScheduleRequestInput
    ) -> EmergencyScheduleRequestView:
        remarks = (data.remarks or "").strip() or None
        if data.decision == "REJECTED" and not remarks:
            raise ValueError("Provide a reason when rejecting an emergency schedule request.")
        if remarks is not None and len(remarks) > MAX_REASON_LENGTH:
            raise ValueError(f"remarks must be at most {MAX_REASON_LENGTH} characters.")
        async with self._uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            reviewer_employee = await _active_employee(uow, data.supervisor_employee_id)
            reviewer_account_employee_id = await uow.session.scalar(
                select(UserModel.employee_id).where(UserModel.id == data.reviewer_user_id)
            )
            if reviewer_account_employee_id != reviewer_employee.id:
                raise ValueError("This account is not linked to the supervisor employee profile.")
            request = await uow.session.scalar(
                select(EmergencyScheduleRequestModel)
                .where(EmergencyScheduleRequestModel.id == data.request_id)
                .with_for_update()
            )
            if request is None:
                raise ValueError("Emergency schedule request not found.")
            if request.status != "PENDING_APPROVAL":
                raise ValueError("This emergency schedule request has already been reviewed.")
            if request.employee_id == data.supervisor_employee_id or request.requested_by == data.reviewer_user_id:
                raise ValueError("You cannot approve your own emergency schedule request.")
            supervisor_assignment = await uow.session.scalar(
                select(EmploymentAssignmentModel.id)
                .where(
                    EmploymentAssignmentModel.employee_id == request.employee_id,
                    EmploymentAssignmentModel.supervisor_employee_id == data.supervisor_employee_id,
                    *_active_employment_conditions(request.work_date),
                )
                .limit(1)
            )
            if supervisor_assignment is None:
                raise ValueError("Only the employee's assigned supervisor may review this request.")
            if data.decision == "APPROVED":
                is_retroactive = request.work_date < ph_today(utc_now())
                if is_retroactive:
                    await _require_current_open_unprocessed_cutoff(
                        uow,
                        request.employee_id,
                        request.work_date,
                        ph_today(utc_now()),
                    )
                template = await _require_template(
                    uow,
                    request.employee_id,
                    request.schedule_template_id,
                    request.work_date,
                )
                if is_retroactive:
                    await _recalculate_attendance_for_emergency_schedule(
                        uow,
                        request,
                        template,
                        data.reviewer_user_id,
                    )
                else:
                    attendance_id = await uow.session.scalar(
                        select(AttendanceModel.id).where(
                            AttendanceModel.user_id == request.requested_by,
                            AttendanceModel.work_date == request.work_date,
                        )
                    )
                    if attendance_id is not None:
                        raise ValueError(
                            "Attendance has already started for this date; the emergency schedule cannot be applied retroactively."
                        )
            request.status = data.decision
            request.reviewed_by = data.reviewer_user_id
            request.reviewed_at = utc_now()
            request.review_remarks = remarks
            await uow.session.flush()
            result = await uow.session.execute(
                _request_query().where(EmergencyScheduleRequestModel.id == request.id)
            )
            row = result.first()
            if row is None:
                raise RuntimeError("The reviewed emergency schedule request could not be reloaded.")
            return _request_view(row)
