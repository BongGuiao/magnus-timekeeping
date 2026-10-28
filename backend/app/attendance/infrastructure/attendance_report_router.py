from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import exists, func, or_, select

from app.attendance.domain.worked_minutes import (
    allocate_official_business_minutes,
    requires_scheduled_work,
    scheduled_work_minutes,
    shift_coverage,
)
from app.attendance.infrastructure.db_model import (
    AttendanceModel,
    OfficialBusinessRequestModel,
    OvertimeApplicationModel,
)
from app.auth.infrastructure.db_model import UserModel
from app.auth.infrastructure.dependencies import (
    get_current_user_claims,
    get_current_authorization_use_case,
    require_any_permission,
    require_permission,
)
from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)
from app.filemaintenance.holidays.calendar.domain.scope import (
    GeographicArea,
    holiday_applies_to_location,
)
from app.filemaintenance.holidays.calendar.infrastructure.db_model import HolidayCalendarModel
from app.filemaintenance.holidays.holiday.infrastructure.db_model import HolidayModel
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import (
    LeaveApplicationDateModel,
    LeaveApplicationModel,
)
from app.filemaintenance.schedule.infrastructure.db_model import ScheduleTemplateModel
from app.filemaintenance.schedule.infrastructure.db_model import (
    EmployeeScheduleAssignmentModel,
    RestDayPatternDayModel,
    RestDayPatternModel,
    ScheduleSegmentModel,
)
from app.filemaintenance.location.infrastructure.db_model import Location as LocationModel
from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import (
    EmployeeCutoffResultModel,
)
from app.filemaintenance.payroll_groups.infrastructure.db_model import PayrollGroupModel

router = APIRouter(prefix="/reports", tags=["Attendance Reports"])
MANILA = ZoneInfo("Asia/Manila")
MAX_REPORT_DAYS = 31
MAX_REPORT_ROWS = 2000


class AttendanceReportOvertime(BaseModel):
    application_no: str
    overtime_type: str
    requested_minutes: int
    approved_minutes: int | None
    payable_minutes: int | None
    status: str


class AttendanceReportLeave(BaseModel):
    application_no: str
    leave_type: str
    requested_minutes: int
    paid_minutes: int
    unpaid_minutes: int
    status: str


class AttendanceReportOfficialBusiness(BaseModel):
    request_no: str
    requested_minutes: int
    approved_minutes: int | None
    credited_minutes: int
    status: str
    start_at: datetime
    end_at: datetime


class AttendanceDetailReportRecord(BaseModel):
    attendance_id: UUID | None
    employee_no: str
    employee_name: str
    work_date: date
    schedule_code: str | None
    expected_clock_in_at: datetime | None
    expected_clock_out_at: datetime | None
    clock_in_at: datetime | None
    clock_out_at: datetime | None
    record_status: str
    attendance_mode: str
    is_absent: bool
    work_type: str
    day_type: str
    late_minutes: int
    undertime_minutes: int
    worked_minutes: int | None
    regular_overtime_minutes: int
    night_differential_minutes: int
    night_differential_overtime_minutes: int
    overtime_applications: list[AttendanceReportOvertime]
    leave_applications: list[AttendanceReportLeave]
    official_business_requests: list[AttendanceReportOfficialBusiness]


class AttendanceFinalizationCutoff(BaseModel):
    cutoff_id: UUID
    cutoff_code: str
    payroll_group_name: str
    period_start: date
    period_end: date
    attendance_deadline: datetime | None
    attendance_finalized_at: datetime | None
    attendance_finalized_by: UUID | None
    attendance_result_count: int


class AttendanceFinalizationResult(BaseModel):
    cutoff_id: UUID
    finalized_at: datetime
    finalized_by: UUID
    attendance_result_count: int


class OrgUnitAttendanceSummary(BaseModel):
    org_unit_id: UUID | None
    org_unit_code: str
    org_unit_name: str
    employee_count: int
    total_attendance: int
    approved_leave_days: int
    approved_leave_minutes: int
    approved_overtime_count: int
    approved_overtime_minutes: int
    approved_ob_count: int
    approved_ob_minutes: int
    regular_overtime_minutes: int
    night_differential_minutes: int
    night_differential_overtime_minutes: int
    late_minutes: int
    undertime_minutes: int


@dataclass
class _OrgUnitAttendanceSummaryAccumulator:
    org_unit_id: UUID | None
    org_unit_code: str
    org_unit_name: str
    employee_ids: set[UUID] = field(default_factory=set)
    attendance_ids: set[UUID] = field(default_factory=set)
    leave_days: set[tuple[UUID, date]] = field(default_factory=set)
    leave_application_ids: set[UUID] = field(default_factory=set)
    approved_leave_minutes: int = 0
    overtime_ids: set[UUID] = field(default_factory=set)
    approved_overtime_minutes: int = 0
    ob_ids: set[UUID] = field(default_factory=set)
    approved_ob_minutes: int = 0
    regular_overtime_minutes: int = 0
    night_differential_minutes: int = 0
    night_differential_overtime_minutes: int = 0
    late_minutes: int = 0
    undertime_minutes: int = 0


def _employee_name(employee: EmployeeModel) -> str:
    preferred_name = employee.preferred_name.strip() if employee.preferred_name else ""
    return preferred_name or " ".join(
        part
        for part in (
            employee.first_name,
            employee.middle_name,
            employee.last_name,
            employee.suffix,
        )
        if part
    )


def _worked_minutes(
    attendance: AttendanceModel,
    required_minutes: int | None,
) -> int | None:
    if attendance.approved_hours_worked is None:
        return None
    return scheduled_work_minutes(
        required_minutes,
        attendance.late_minutes,
        attendance.undertime_minutes,
        attendance.work_type,
        attendance.day_type,
    )


def _attendance_mode_for_date(
    assignments: list[tuple[EmployeeScheduleAssignmentModel, int | None]],
    work_date: date,
) -> str:
    for assignment, _ in assignments:
        if (
            assignment.effective_from <= work_date
            and (assignment.effective_to is None or assignment.effective_to >= work_date)
        ):
            return (
                "SCHEDULE_CREDITED"
                if assignment.attendance_mode == "SCHEDULE_CREDITED"
                else "PUNCH_REQUIRED"
            )
    return "PUNCH_REQUIRED"


def _attach_official_business(
    coverage_inputs: list[tuple[UUID, "AttendanceDetailReportRecord", int | None]],
    requests_by_employee: dict[UUID, list[OfficialBusinessRequestModel]],
    from_date: date,
    to_date: date,
) -> None:
    """Show each request on the dates it touches with the minutes credited by payroll."""
    records_by_key: dict[tuple[UUID, date], AttendanceDetailReportRecord] = {}
    shifts_by_employee: dict[UUID, list] = {}
    for employee_id, record, required_minutes in coverage_inputs:
        records_by_key[(employee_id, record.work_date)] = record
        approved_leave_minutes = min(
            max(required_minutes or 0, 0),
            sum(
                leave.paid_minutes + leave.unpaid_minutes
                for leave in record.leave_applications
                if leave.status == "APPROVED"
            ),
        ) if record.attendance_mode == "SCHEDULE_CREDITED" else 0
        coverage = shift_coverage(
            work_date=record.work_date,
            expected_clock_in_at=record.expected_clock_in_at,
            expected_clock_out_at=record.expected_clock_out_at,
            required_minutes=required_minutes,
            credited_work_minutes=(
                approved_leave_minutes
                if record.attendance_mode == "SCHEDULE_CREDITED"
                else (0 if record.is_absent else record.worked_minutes or 0)
            ),
            work_type=record.work_type,
            day_type=record.day_type,
            clock_in_at=(
                None
                if record.is_absent or record.attendance_mode == "SCHEDULE_CREDITED"
                else record.clock_in_at
            ),
            clock_out_at=(
                None
                if record.is_absent or record.attendance_mode == "SCHEDULE_CREDITED"
                else record.clock_out_at
            ),
        )
        if coverage is not None:
            shifts_by_employee.setdefault(employee_id, []).append(coverage)

    for employee_id, requests in requests_by_employee.items():
        used: dict[date, int] = {}
        for request in sorted(requests, key=lambda item: item.start_at):
            credited = (
                allocate_official_business_minutes(
                    request.start_at,
                    request.end_at,
                    request.approved_minutes or 0,
                    shifts_by_employee.get(employee_id, []),
                    used,
                )
                if request.status == "APPROVED"
                else {}
            )
            dates = set(credited)
            day = request.start_at.astimezone(MANILA).date()
            while day <= request.end_at.astimezone(MANILA).date():
                dates.add(day)
                day += timedelta(days=1)
            for work_date in sorted(dates):
                record = records_by_key.get((employee_id, work_date))
                if record is None or not from_date <= work_date <= to_date:
                    continue
                record.official_business_requests.append(
                    AttendanceReportOfficialBusiness(
                        request_no=request.request_no,
                        requested_minutes=request.requested_minutes,
                        approved_minutes=request.approved_minutes,
                        credited_minutes=credited.get(work_date, 0),
                        status=request.status,
                        start_at=request.start_at,
                        end_at=request.end_at,
                    )
                )

    for _, record, required_minutes in coverage_inputs:
        if record.attendance_mode != "SCHEDULE_CREDITED":
            continue
        if record.is_absent:
            record.worked_minutes = 0
            continue
        if not requires_scheduled_work(record.work_type, record.day_type):
            record.worked_minutes = 0
            continue
        scheduled_minutes = max(required_minutes or 0, 0)
        leave_minutes = min(
            scheduled_minutes,
            sum(
                leave.paid_minutes + leave.unpaid_minutes
                for leave in record.leave_applications
                if leave.status == "APPROVED"
            ),
        )
        official_business_minutes = min(
            max(scheduled_minutes - leave_minutes, 0),
            sum(
                business.credited_minutes
                for business in record.official_business_requests
                if business.status == "APPROVED"
            ),
        )
        record.worked_minutes = max(
            scheduled_minutes - leave_minutes - official_business_minutes,
            0,
        )


def _holiday_day_type(holiday_type: str, is_double_holiday: bool) -> str | None:
    if is_double_holiday:
        return "DBL"
    return {
        "REGULAR": "RH",
        "SPECIAL_NONWORKING": "SNW",
        "SPECIAL_WORKING": "SWH",
        "LOCAL": "LOC",
        "COMPANY": "COM",
    }.get(holiday_type)


def _cycle_day_number(effective_from: date, work_date: date, cycle_length_days: int) -> int:
    if cycle_length_days == 7:
        return work_date.weekday() + 1
    return ((work_date - effective_from).days % cycle_length_days) + 1


@router.get(
    "/attendance-summary-by-org-unit",
    response_model=ResponseEnvelope[list[OrgUnitAttendanceSummary]],
)
async def get_attendance_summary_by_org_unit(
    from_date: date = Query(...),
    to_date: date = Query(...),
    claims: dict = Depends(require_permission("payroll.manage")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    del claims
    if to_date < from_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="to_date must be on or after from_date.",
        )
    if (to_date - from_date).days >= MAX_REPORT_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Attendance summaries are limited to {MAX_REPORT_DAYS} days. Narrow the date range.",
        )

    start_at = datetime.combine(from_date, time.min, tzinfo=MANILA)
    end_at = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=MANILA)
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")

        buckets: dict[UUID | None, _OrgUnitAttendanceSummaryAccumulator] = {
            unit.id: _OrgUnitAttendanceSummaryAccumulator(
                org_unit_id=unit.id,
                org_unit_code=unit.org_unit_code,
                org_unit_name=unit.org_unit_name,
            )
            for unit in (
                await session.scalars(
                    select(OrgUnit).where(
                        OrgUnit.is_active.is_(True),
                        OrgUnit.status == "ACTIVE",
                        OrgUnit.effective_from <= to_date,
                        or_(
                            OrgUnit.effective_to.is_(None),
                            OrgUnit.effective_to >= from_date,
                        ),
                    )
                )
            ).all()
        }
        buckets[None] = _OrgUnitAttendanceSummaryAccumulator(
            org_unit_id=None,
            org_unit_code="UNASSIGNED",
            org_unit_name="Unassigned",
        )

        employment_rows = (
            await session.execute(
                select(EmploymentAssignmentModel, OrgUnit)
                .outerjoin(
                    OrgUnit,
                    OrgUnit.id == EmploymentAssignmentModel.org_unit_id,
                )
                .where(
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.effective_from <= to_date,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= from_date,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= from_date,
                    ),
                )
                .order_by(EmploymentAssignmentModel.effective_from.desc())
            )
        ).all()
        employment_by_employee: dict[
            UUID, list[tuple[EmploymentAssignmentModel, OrgUnit | None]]
        ] = {}
        for employment, org_unit in employment_rows:
            employment_by_employee.setdefault(employment.employee_id, []).append(
                (employment, org_unit)
            )

        def bucket_for(employee_id: UUID, work_date: date) -> _OrgUnitAttendanceSummaryAccumulator:
            matching_assignment = next(
                (
                    (employment, org_unit)
                    for employment, org_unit in employment_by_employee.get(employee_id, [])
                    if employment.effective_from <= work_date
                    and (
                        employment.effective_to is None
                        or employment.effective_to >= work_date
                    )
                    and (
                        employment.separation_date is None
                        or employment.separation_date >= work_date
                    )
                ),
                None,
            )
            if matching_assignment is None or matching_assignment[1] is None:
                return buckets[None]
            _, org_unit = matching_assignment
            if org_unit is None:
                return buckets[None]
            return buckets.setdefault(
                org_unit.id,
                _OrgUnitAttendanceSummaryAccumulator(
                    org_unit_id=org_unit.id,
                    org_unit_code=org_unit.org_unit_code,
                    org_unit_name=org_unit.org_unit_name,
                ),
            )

        attendance_rows = (
            await session.execute(
                select(AttendanceModel, UserModel.employee_id)
                .join(UserModel, UserModel.id == AttendanceModel.user_id)
                .where(
                    AttendanceModel.work_date >= from_date,
                    AttendanceModel.work_date <= to_date,
                    AttendanceModel.record_status == "VALID",
                    UserModel.employee_id.is_not(None),
                )
            )
        ).all()
        for attendance, employee_id in attendance_rows:
            if employee_id is None:
                continue
            bucket = bucket_for(employee_id, attendance.work_date)
            bucket.employee_ids.add(employee_id)
            bucket.attendance_ids.add(attendance.id)
            bucket.regular_overtime_minutes += attendance.approved_regular_overtime_minutes
            bucket.night_differential_minutes += attendance.approved_night_differential_minutes
            bucket.night_differential_overtime_minutes += (
                attendance.approved_night_differential_overtime_minutes
            )
            bucket.late_minutes += attendance.late_minutes
            bucket.undertime_minutes += attendance.undertime_minutes

        leave_rows = (
            await session.execute(
                select(
                    LeaveApplicationModel,
                    LeaveApplicationDateModel,
                )
                .join(
                    LeaveApplicationDateModel,
                    LeaveApplicationDateModel.leave_application_id
                    == LeaveApplicationModel.id,
                )
                .where(
                    LeaveApplicationModel.is_active.is_(True),
                    LeaveApplicationModel.status == "APPROVED",
                    LeaveApplicationDateModel.leave_date >= from_date,
                    LeaveApplicationDateModel.leave_date <= to_date,
                )
            )
        ).all()
        for application, application_date in leave_rows:
            bucket = bucket_for(application.employee_id, application_date.leave_date)
            bucket.employee_ids.add(application.employee_id)
            bucket.leave_days.add((application.employee_id, application_date.leave_date))
            bucket.leave_application_ids.add(application.id)
            bucket.approved_leave_minutes += (
                application_date.approved_paid_minutes
                + application_date.approved_unpaid_minutes
            )

        overtime_rows = (
            await session.scalars(
                select(OvertimeApplicationModel).where(
                    OvertimeApplicationModel.is_active.is_(True),
                    OvertimeApplicationModel.status == "APPROVED",
                    OvertimeApplicationModel.attendance_date >= from_date,
                    OvertimeApplicationModel.attendance_date <= to_date,
                )
            )
        ).all()
        for application in overtime_rows:
            bucket = bucket_for(application.employee_id, application.attendance_date)
            bucket.employee_ids.add(application.employee_id)
            bucket.overtime_ids.add(application.id)
            bucket.approved_overtime_minutes += (
                application.final_payable_minutes
                if application.final_payable_minutes is not None
                else application.supervisor_approved_minutes or 0
            )

        business_rows = (
            await session.scalars(
                select(OfficialBusinessRequestModel).where(
                    OfficialBusinessRequestModel.is_active.is_(True),
                    OfficialBusinessRequestModel.status == "APPROVED",
                    OfficialBusinessRequestModel.start_at >= start_at,
                    OfficialBusinessRequestModel.start_at < end_at,
                )
            )
        ).all()
        for request in business_rows:
            request_date = request.start_at.astimezone(MANILA).date()
            bucket = bucket_for(request.employee_id, request_date)
            bucket.employee_ids.add(request.employee_id)
            bucket.ob_ids.add(request.id)
            bucket.approved_ob_minutes += request.approved_minutes or 0

    summaries = [
        OrgUnitAttendanceSummary(
            org_unit_id=bucket.org_unit_id,
            org_unit_code=bucket.org_unit_code,
            org_unit_name=bucket.org_unit_name,
            employee_count=len(bucket.employee_ids),
            total_attendance=len(bucket.attendance_ids),
            approved_leave_days=len(bucket.leave_days),
            approved_leave_minutes=bucket.approved_leave_minutes,
            approved_overtime_count=len(bucket.overtime_ids),
            approved_overtime_minutes=bucket.approved_overtime_minutes,
            approved_ob_count=len(bucket.ob_ids),
            approved_ob_minutes=bucket.approved_ob_minutes,
            regular_overtime_minutes=bucket.regular_overtime_minutes,
            night_differential_minutes=bucket.night_differential_minutes,
            night_differential_overtime_minutes=bucket.night_differential_overtime_minutes,
            late_minutes=bucket.late_minutes,
            undertime_minutes=bucket.undertime_minutes,
        )
        for bucket in buckets.values()
        if bucket.org_unit_id is not None or bucket.employee_ids
    ]
    summaries.sort(key=lambda summary: (summary.org_unit_name == "Unassigned", summary.org_unit_name.casefold()))
    return ResponseEnvelope(status="success", data=summaries)


@router.get(
    "/attendance-cutoffs",
    response_model=ResponseEnvelope[list[AttendanceFinalizationCutoff]],
)
async def list_attendance_finalization_cutoffs(
    claims: dict = Depends(
        require_any_permission("attendance.read_org", "payroll.manage")
    ),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    del claims
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        rows = (
            await session.execute(
                select(
                    PayrollCutoffModel,
                    PayrollGroupModel.payroll_group_name,
                    func.count(EmployeeCutoffResultModel.id),
                )
                .join(
                    PayrollGroupModel,
                    PayrollGroupModel.id == PayrollCutoffModel.payroll_group_id,
                )
                .outerjoin(
                    EmployeeCutoffResultModel,
                    EmployeeCutoffResultModel.cutoff_id == PayrollCutoffModel.id,
                )
                .where(PayrollCutoffModel.is_active.is_(True))
                .group_by(PayrollCutoffModel.id, PayrollGroupModel.payroll_group_name)
                .order_by(PayrollCutoffModel.period_start.desc(), PayrollCutoffModel.cutoff_code)
                .limit(1000)
            )
        ).all()
    cutoffs = [
        AttendanceFinalizationCutoff(
            cutoff_id=cutoff.id,
            cutoff_code=cutoff.cutoff_code,
            payroll_group_name=group_name,
            period_start=cutoff.period_start,
            period_end=cutoff.period_end,
            attendance_deadline=cutoff.attendance_deadline,
            attendance_finalized_at=cutoff.attendance_finalized_at,
            attendance_finalized_by=cutoff.attendance_finalized_by,
            attendance_result_count=result_count,
        )
        for cutoff, group_name, result_count in rows
    ]
    return ResponseEnvelope(status="success", data=cutoffs)


@router.post(
    "/attendance-cutoffs/{cutoff_id}/finalize",
    response_model=ResponseEnvelope[AttendanceFinalizationResult],
    dependencies=[Depends(require_permission("attendance.finalize"))],
)
async def finalize_attendance_cutoff(
    cutoff_id: UUID,
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    try:
        actor_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error

    finalized_at = datetime.now(timezone.utc)
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        cutoff = await session.scalar(
            select(PayrollCutoffModel)
            .where(
                PayrollCutoffModel.id == cutoff_id,
                PayrollCutoffModel.is_active.is_(True),
            )
            .with_for_update()
        )
        if cutoff is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payroll cutoff not found.",
            )
        if cutoff.attendance_finalized_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attendance for this cutoff has already been finalized.",
            )
        if cutoff.locked_at is not None or cutoff.status.upper() == "LOCKED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Payroll is already locked; attendance cannot be finalized afterward.",
            )
        if cutoff.attendance_deadline is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Set the cutoff attendance deadline before finalizing attendance.",
            )
        if finalized_at <= cutoff.attendance_deadline:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attendance can be finalized only after its cutoff deadline has passed.",
            )
        result_count = await session.scalar(
            select(func.count(EmployeeCutoffResultModel.id)).where(
                EmployeeCutoffResultModel.cutoff_id == cutoff_id,
                EmployeeCutoffResultModel.calculated_at.is_not(None),
            )
        )
        if not cutoff.calculation_version or not result_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Calculate attendance results for this cutoff before finalizing attendance.",
            )
        cutoff.attendance_finalized_at = finalized_at
        cutoff.attendance_finalized_by = actor_id
        cutoff.updated_at = finalized_at
        cutoff.updated_by = actor_id
        cutoff.row_version += 1
        await session.flush()
        result = AttendanceFinalizationResult(
            cutoff_id=cutoff.id,
            finalized_at=finalized_at,
            finalized_by=actor_id,
            attendance_result_count=result_count,
        )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/attendance-detail",
    response_model=ResponseEnvelope[list[AttendanceDetailReportRecord]],
)
async def get_attendance_detail_report(
    from_date: date = Query(...),
    to_date: date = Query(...),
    scope: str = Query(..., pattern="^(own|team|organization)$"),
    employee_no: str | None = Query(default=None, min_length=1, max_length=30),
    cutoff_id: UUID | None = Query(default=None),
    claims: dict = Depends(
        require_any_permission(
            "attendance.read_own",
            "attendance.read_team",
            "attendance.read_org",
            "payroll.manage",
        )
    ),
    authorization_use_case: GetCurrentAuthorizationUseCase = Depends(
        get_current_authorization_use_case
    ),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    if to_date < from_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="to_date must be on or after from_date.",
        )
    if (to_date - from_date).days >= MAX_REPORT_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Attendance detail reports are limited to {MAX_REPORT_DAYS} days. Narrow the date range.",
        )

    cutoff_start = datetime.combine(from_date, time.min, tzinfo=MANILA)
    cutoff_end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=MANILA)
    authorization = await authorization_use_case.execute(UUID(str(claims["sub"])))
    permission_codes = set(authorization.permission_codes)
    if scope == "own" and "attendance.read_own" not in permission_codes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
    if scope == "team" and "attendance.read_team" not in permission_codes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
    if scope == "organization" and not permission_codes.intersection(
        {"attendance.read_org", "payroll.manage"}
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")

    try:
        employee_id = UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError):
        employee_id = None
    if scope in {"own", "team"} and employee_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to an employee profile.",
        )

    team_scope = None
    if scope == "team":
        team_scope = exists(
            select(1).where(
                EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                EmploymentAssignmentModel.supervisor_employee_id == employee_id,
                EmploymentAssignmentModel.is_active.is_(True),
                EmploymentAssignmentModel.status == "ACTIVE",
                EmploymentAssignmentModel.effective_from <= to_date,
                or_(
                    EmploymentAssignmentModel.effective_to.is_(None),
                    EmploymentAssignmentModel.effective_to >= from_date,
                ),
                or_(
                    EmploymentAssignmentModel.separation_date.is_(None),
                    EmploymentAssignmentModel.separation_date >= from_date,
                ),
            )
        )

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")

        selected_payroll_group_id = None
        if cutoff_id is not None:
            selected_cutoff = await session.scalar(
                select(PayrollCutoffModel).where(
                    PayrollCutoffModel.id == cutoff_id,
                    PayrollCutoffModel.is_active.is_(True),
                )
            )
            if selected_cutoff is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Payroll cutoff not found.",
                )
            if (
                selected_cutoff.period_start != from_date
                or selected_cutoff.period_end != to_date
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="The report dates must match the selected payroll cutoff.",
                )
            selected_payroll_group_id = selected_cutoff.payroll_group_id

        statement = (
            select(
                AttendanceModel,
                EmployeeModel,
                ScheduleTemplateModel.schedule_code,
                ScheduleTemplateModel.required_minutes,
            )
            .join(
                UserModel,
                UserModel.id == AttendanceModel.user_id,
            )
            .join(
                EmployeeModel,
                EmployeeModel.id == UserModel.employee_id,
            )
            .outerjoin(
                ScheduleTemplateModel,
                ScheduleTemplateModel.id == AttendanceModel.schedule_template_id,
            )
            .where(
                AttendanceModel.work_date >= from_date,
                AttendanceModel.work_date <= to_date,
                AttendanceModel.record_status == "VALID",
            )
            .order_by(EmployeeModel.employee_no, AttendanceModel.work_date)
            .limit(MAX_REPORT_ROWS + 1)
        )
        if employee_no:
            statement = statement.where(
                EmployeeModel.employee_no == employee_no.strip().upper()
            )
        if selected_payroll_group_id is not None:
            statement = statement.where(
                exists(
                    select(1).where(
                        EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                        EmploymentAssignmentModel.payroll_group_id
                        == selected_payroll_group_id,
                        EmploymentAssignmentModel.is_active.is_(True),
                        EmploymentAssignmentModel.status == "ACTIVE",
                        EmploymentAssignmentModel.effective_from
                        <= AttendanceModel.work_date,
                        or_(
                            EmploymentAssignmentModel.effective_to.is_(None),
                            EmploymentAssignmentModel.effective_to
                            >= AttendanceModel.work_date,
                        ),
                        or_(
                            EmploymentAssignmentModel.separation_date.is_(None),
                            EmploymentAssignmentModel.separation_date
                            >= AttendanceModel.work_date,
                        ),
                    )
                )
            )
        if scope == "own":
            statement = statement.where(EmployeeModel.id == employee_id)
        elif team_scope is not None:
            statement = statement.where(team_scope)

        rows = (await session.execute(statement)).all()
        if len(rows) > MAX_REPORT_ROWS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"The report exceeds {MAX_REPORT_ROWS} attendance rows. Narrow the date range or filter by employee number.",
            )

        attendance_ids = [attendance.id for attendance, _, _, _ in rows]
        employees_by_id = {employee.id: employee for _, employee, _, _ in rows}
        schedule_assignments = (
            await session.execute(
                select(
                    EmployeeScheduleAssignmentModel,
                    RestDayPatternModel.cycle_length_days,
                    EmployeeModel,
                    UserModel.id,
                )
                .join(
                    EmployeeModel,
                    EmployeeModel.id == EmployeeScheduleAssignmentModel.employee_id,
                )
                .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                .outerjoin(
                    RestDayPatternModel,
                    RestDayPatternModel.id
                    == EmployeeScheduleAssignmentModel.rest_day_pattern_id,
                )
                .where(
                    EmployeeScheduleAssignmentModel.is_active.is_(True),
                    EmployeeScheduleAssignmentModel.status.in_(("ACTIVE", "APPROVED")),
                    EmployeeScheduleAssignmentModel.effective_from <= to_date,
                    or_(
                        EmployeeScheduleAssignmentModel.effective_to.is_(None),
                        EmployeeScheduleAssignmentModel.effective_to >= from_date,
                    ),
                    EmployeeModel.is_active.is_(True),
                    UserModel.is_active.is_(True),
                    *(
                        [
                            exists(
                                select(1).where(
                                    EmploymentAssignmentModel.employee_id
                                    == EmployeeModel.id,
                                    EmploymentAssignmentModel.payroll_group_id
                                    == selected_payroll_group_id,
                                    EmploymentAssignmentModel.is_active.is_(True),
                                    EmploymentAssignmentModel.status == "ACTIVE",
                                    EmploymentAssignmentModel.effective_from
                                    <= to_date,
                                    or_(
                                        EmploymentAssignmentModel.effective_to.is_(None),
                                        EmploymentAssignmentModel.effective_to
                                        >= from_date,
                                    ),
                                    or_(
                                        EmploymentAssignmentModel.separation_date.is_(None),
                                        EmploymentAssignmentModel.separation_date
                                        >= from_date,
                                    ),
                                )
                            )
                        ]
                        if selected_payroll_group_id is not None
                        else []
                    ),
                    *(
                        [EmployeeModel.id == employee_id]
                        if scope == "own" and employee_id is not None
                        else [team_scope] if team_scope is not None else []
                    ),
                    *(
                        [EmployeeModel.employee_no == employee_no.strip().upper()]
                        if employee_no
                        else []
                    ),
                )
                .order_by(
                    EmployeeScheduleAssignmentModel.effective_from.desc(),
                    EmployeeScheduleAssignmentModel.created_at.desc(),
                )
            )
        ).all()
        assignments_by_employee: dict[
            UUID, list[tuple[EmployeeScheduleAssignmentModel, int | None]]
        ] = {}
        user_id_by_employee: dict[UUID, UUID] = {}
        for assignment, cycle_length, employee, user_id in schedule_assignments:
            employees_by_id[employee.id] = employee
            user_id_by_employee[employee.id] = user_id
            assignments_by_employee.setdefault(employee.id, []).append(
                (assignment, cycle_length)
            )

        employee_ids = set(employees_by_id)
        overtime_by_attendance: dict[UUID, list[AttendanceReportOvertime]] = {}
        leave_by_employee_date: dict[tuple[UUID, date], list[AttendanceReportLeave]] = {}
        official_business_by_employee_date: dict[
            tuple[UUID, date], list[AttendanceReportOfficialBusiness]
        ] = {}
        business_requests_by_employee: dict[UUID, list[OfficialBusinessRequestModel]] = {}

        if attendance_ids:
            overtime_rows = (
                await session.scalars(
                    select(OvertimeApplicationModel)
                    .where(
                        OvertimeApplicationModel.attendance_record_id.in_(attendance_ids),
                        OvertimeApplicationModel.is_active.is_(True),
                    )
                    .order_by(OvertimeApplicationModel.created_at)
                )
            ).all()
            for application in overtime_rows:
                overtime_by_attendance.setdefault(
                    application.attendance_record_id, []
                ).append(
                    AttendanceReportOvertime(
                        application_no=application.application_no,
                        overtime_type=application.overtime_type,
                        requested_minutes=application.requested_minutes,
                        approved_minutes=application.supervisor_approved_minutes,
                        payable_minutes=application.final_payable_minutes,
                        status=application.status,
                    )
                )

        if employee_ids:
            leave_rows = (
                await session.execute(
                    select(
                        LeaveApplicationModel,
                        LeaveApplicationDateModel,
                        LeaveTypeModel.leave_code,
                    )
                    .join(
                        LeaveApplicationDateModel,
                        LeaveApplicationDateModel.leave_application_id
                        == LeaveApplicationModel.id,
                    )
                    .join(
                        LeaveTypeModel,
                        LeaveTypeModel.id == LeaveApplicationModel.leave_type_id,
                    )
                    .where(
                        LeaveApplicationModel.employee_id.in_(employee_ids),
                        LeaveApplicationModel.is_active.is_(True),
                        LeaveApplicationDateModel.leave_date >= from_date,
                        LeaveApplicationDateModel.leave_date <= to_date,
                    )
                    .order_by(LeaveApplicationModel.created_at)
                )
            ).all()
            for application, application_date, leave_code in leave_rows:
                leave_by_employee_date.setdefault(
                    (application.employee_id, application_date.leave_date), []
                ).append(
                    AttendanceReportLeave(
                        application_no=application.application_no,
                        leave_type=leave_code,
                        requested_minutes=application_date.requested_minutes,
                        paid_minutes=application_date.approved_paid_minutes,
                        unpaid_minutes=application_date.approved_unpaid_minutes,
                        status=application.status,
                    )
                )

            business_rows = (
                await session.scalars(
                    select(OfficialBusinessRequestModel)
                    .where(
                        OfficialBusinessRequestModel.employee_id.in_(employee_ids),
                        OfficialBusinessRequestModel.is_active.is_(True),
                        OfficialBusinessRequestModel.start_at < cutoff_end,
                        OfficialBusinessRequestModel.end_at > cutoff_start,
                    )
                    .order_by(OfficialBusinessRequestModel.start_at)
                )
            ).all()
            for request in business_rows:
                business_requests_by_employee.setdefault(request.employee_id, []).append(request)

        template_ids = {
            assignment.schedule_template_id
            for assignment_rows in assignments_by_employee.values()
            for assignment, _ in assignment_rows
        }
        pattern_days: dict[tuple[UUID, int], RestDayPatternDayModel] = {}
        pattern_ids = {
            assignment.rest_day_pattern_id
            for assignment_rows in assignments_by_employee.values()
            for assignment, _ in assignment_rows
            if assignment.rest_day_pattern_id is not None
        }
        if pattern_ids:
            pattern_days = {
                (pattern_day.pattern_id, pattern_day.cycle_day_no): pattern_day
                for pattern_day in (
                    await session.scalars(
                        select(RestDayPatternDayModel).where(
                            RestDayPatternDayModel.pattern_id.in_(pattern_ids)
                        )
                    )
                ).all()
            }
        all_pattern_template_ids = {
            pattern_day.schedule_template_id
            for pattern_day in pattern_days.values()
            if pattern_day.schedule_template_id is not None
        }
        template_ids.update(all_pattern_template_ids)
        templates = {
            template.id: template
            for template in (
                await session.scalars(
                    select(ScheduleTemplateModel).where(
                        ScheduleTemplateModel.id.in_(template_ids)
                    )
                )
            ).all()
        } if template_ids else {}
        work_segments_by_template: dict[UUID, list[ScheduleSegmentModel]] = {}
        if template_ids:
            for segment in (
                await session.scalars(
                    select(ScheduleSegmentModel)
                    .where(
                        ScheduleSegmentModel.schedule_template_id.in_(template_ids),
                        ScheduleSegmentModel.segment_type == "WORK",
                    )
                    .order_by(ScheduleSegmentModel.segment_sequence)
                )
            ).all():
                work_segments_by_template.setdefault(
                    segment.schedule_template_id, []
                ).append(segment)

        employment_rows = (
            await session.execute(
                select(
                    EmploymentAssignmentModel,
                    LocationModel.region,
                    LocationModel.province,
                    LocationModel.city,
                    LocationModel.psgc_region_code,
                    LocationModel.psgc_province_code,
                    LocationModel.psgc_city_code,
                    LocationModel.ncr_district,
                )
                .outerjoin(
                    LocationModel,
                    LocationModel.id == EmploymentAssignmentModel.primary_location_id,
                )
                .where(
                    EmploymentAssignmentModel.employee_id.in_(employee_ids)
                    if employee_ids
                    else False,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    *(
                        [
                            EmploymentAssignmentModel.payroll_group_id
                            == selected_payroll_group_id
                        ]
                        if selected_payroll_group_id is not None
                        else []
                    ),
                    EmploymentAssignmentModel.effective_from <= to_date,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= from_date,
                    ),
                )
                .order_by(EmploymentAssignmentModel.effective_from.desc())
            )
        ).all() if employee_ids else []
        employment_by_employee: dict[UUID, list[tuple[EmploymentAssignmentModel, GeographicArea]]] = {}
        company_ids: set[UUID] = set()
        for (
            employment,
            region,
            province,
            city,
            psgc_region_code,
            psgc_province_code,
            psgc_city_code,
            ncr_district,
        ) in employment_rows:
            employment_by_employee.setdefault(employment.employee_id, []).append(
                (
                    employment,
                    GeographicArea(
                        region=region,
                        province=province,
                        city=city,
                        psgc_region_code=psgc_region_code,
                        psgc_province_code=psgc_province_code,
                        psgc_city_code=psgc_city_code,
                        ncr_district=ncr_district,
                    ),
                )
            )
            company_ids.add(employment.company_id)

        calendars = (
            await session.scalars(
                select(HolidayCalendarModel).where(
                    HolidayCalendarModel.company_id.in_(company_ids),
                    HolidayCalendarModel.effective_year >= from_date.year,
                    HolidayCalendarModel.effective_year <= to_date.year,
                    HolidayCalendarModel.status == "PUBLISHED",
                    HolidayCalendarModel.is_active.is_(True),
                )
            )
        ).all() if company_ids else []
        calendars_by_id = {calendar.id: calendar for calendar in calendars}
        holidays_by_date: dict[date, list[tuple[HolidayModel, HolidayCalendarModel]]] = {}
        if calendars_by_id:
            holidays = (
                await session.scalars(
                    select(HolidayModel).where(
                        HolidayModel.holiday_calendar_id.in_(calendars_by_id),
                        HolidayModel.holiday_date >= from_date,
                        HolidayModel.holiday_date <= to_date,
                        HolidayModel.status == "ACTIVE",
                        HolidayModel.is_active.is_(True),
                    )
                )
            ).all()
            for holiday in holidays:
                calendar = calendars_by_id[holiday.holiday_calendar_id]
                holidays_by_date.setdefault(holiday.holiday_date, []).append(
                    (holiday, calendar)
                )

        def calendar_day_type(employee_id: UUID, work_date: date) -> str:
            employment_matches = [
                employment
                for employment, _ in employment_by_employee.get(employee_id, [])
                if employment.effective_from <= work_date
                and (
                    employment.effective_to is None
                    or employment.effective_to >= work_date
                )
            ]
            if not employment_matches:
                return "REG"
            employment = employment_matches[0]
            location = next(
                (
                    area
                    for candidate, area in employment_by_employee[employee_id]
                    if candidate.id == employment.id
                ),
                GeographicArea(),
            )

            priorities = ("DBL", "RH", "SNW", "LOC", "COM", "SWH")
            matches: list[str] = []
            for holiday, calendar in holidays_by_date.get(work_date, []):
                if calendar.company_id != employment.company_id:
                    continue
                if calendar.effective_year != work_date.year:
                    continue
                if not holiday_applies_to_location(
                    holiday.holiday_type,
                    holiday,
                    location,
                ):
                    continue
                code = _holiday_day_type(holiday.holiday_type, holiday.is_double_holiday)
                if code:
                    matches.append(code)
            return min(matches, key=priorities.index) if matches else "REG"

        report_records = [
            AttendanceDetailReportRecord(
                    attendance_id=attendance.id,
                    employee_no=employee.employee_no,
                    employee_name=_employee_name(employee),
                    work_date=attendance.work_date,
                    schedule_code=schedule_code,
                    expected_clock_in_at=attendance.expected_clock_in_at,
                    expected_clock_out_at=attendance.expected_clock_out_at,
                    clock_in_at=attendance.corrected_clock_in_at
                    or attendance.clock_in_at,
                    clock_out_at=attendance.corrected_clock_out_at
                    or attendance.clock_out_at,
                    record_status=attendance.record_status,
                    attendance_mode=_attendance_mode_for_date(
                        assignments_by_employee.get(employee.id, []),
                        attendance.work_date,
                    ),
                    is_absent=attendance.is_absent,
                    work_type=attendance.work_type,
                    day_type=attendance.day_type,
                    late_minutes=(
                        0
                        if _attendance_mode_for_date(
                            assignments_by_employee.get(employee.id, []),
                            attendance.work_date,
                        ) == "SCHEDULE_CREDITED"
                        else attendance.late_minutes
                    ),
                    undertime_minutes=(
                        0
                        if _attendance_mode_for_date(
                            assignments_by_employee.get(employee.id, []),
                            attendance.work_date,
                        ) == "SCHEDULE_CREDITED"
                        else attendance.undertime_minutes
                    ),
                    worked_minutes=(
                        None
                        if _attendance_mode_for_date(
                            assignments_by_employee.get(employee.id, []),
                            attendance.work_date,
                        ) == "SCHEDULE_CREDITED"
                        else _worked_minutes(attendance, required_minutes)
                    ),
                    regular_overtime_minutes=attendance.regular_overtime_minutes,
                    night_differential_minutes=attendance.night_differential_minutes,
                    night_differential_overtime_minutes=(
                        attendance.night_differential_overtime_minutes
                    ),
                    overtime_applications=overtime_by_attendance.get(
                        attendance.id, []
                    ),
                    leave_applications=leave_by_employee_date.get(
                        (employee.id, attendance.work_date), []
                    ),
                    official_business_requests=official_business_by_employee_date.get(
                        (employee.id, attendance.work_date), []
                    ),
                )
                for attendance, employee, schedule_code, required_minutes in rows
        ]
        coverage_inputs: list[tuple[UUID, AttendanceDetailReportRecord, int | None]] = [
            (employee.id, record, required_minutes)
            for (_, employee, _, required_minutes), record in zip(rows, report_records)
        ]

        existing_attendance_dates = {
            (attendance.user_id, attendance.work_date)
            for attendance, _, _, _ in rows
        }
        for employee_id, assigned_rows in assignments_by_employee.items():
            employee = employees_by_id[employee_id]
            for work_date_offset in range((to_date - from_date).days + 1):
                work_date = from_date + timedelta(days=work_date_offset)
                active_assignments = [
                    (assignment, cycle_length)
                    for assignment, cycle_length in assigned_rows
                    if assignment.effective_from <= work_date
                    and (
                        assignment.effective_to is None
                        or assignment.effective_to >= work_date
                    )
                ]
                if not active_assignments:
                    continue
                if selected_payroll_group_id is not None and not any(
                    employment.payroll_group_id == selected_payroll_group_id
                    and employment.effective_from <= work_date
                    and (
                        employment.effective_to is None
                        or employment.effective_to >= work_date
                    )
                    and (
                        employment.separation_date is None
                        or employment.separation_date >= work_date
                    )
                    for employment, _ in employment_by_employee.get(employee_id, [])
                ):
                    continue
                assignment, cycle_length = active_assignments[0]
                selected_template_id = assignment.schedule_template_id
                is_workday = True
                if assignment.rest_day_pattern_id is not None:
                    if cycle_length is None:
                        raise RuntimeError("The assigned rest-day pattern could not be loaded.")
                    cycle_day = _cycle_day_number(
                        assignment.effective_from, work_date, cycle_length
                    )
                    pattern_day = pattern_days.get(
                        (assignment.rest_day_pattern_id, cycle_day)
                    )
                    if pattern_day is None:
                        raise RuntimeError(
                            f"The assigned rest-day pattern is missing cycle day {cycle_day}."
                        )
                    is_workday = pattern_day.is_workday
                    selected_template_id = (
                        pattern_day.schedule_template_id or selected_template_id
                    )
                if (user_id_by_employee[employee_id], work_date) in existing_attendance_dates:
                    continue
                template = templates.get(selected_template_id) if selected_template_id else None
                segments = work_segments_by_template.get(selected_template_id, [])
                if is_workday and (template is None or not segments):
                    raise RuntimeError(
                        f"The assigned schedule template for {employee.employee_no} on {work_date} could not be loaded."
                    )
                report_records.append(
                    AttendanceDetailReportRecord(
                        attendance_id=None,
                        employee_no=employee.employee_no,
                        employee_name=_employee_name(employee),
                        work_date=work_date,
                        schedule_code=template.schedule_code if template else None,
                        expected_clock_in_at=(
                            datetime.combine(
                                work_date, segments[0].start_time, tzinfo=MANILA
                            )
                            if is_workday
                            else None
                        ),
                        expected_clock_out_at=(
                            datetime.combine(
                                work_date + timedelta(days=segments[-1].end_day_offset),
                                segments[-1].end_time,
                                tzinfo=MANILA,
                            )
                            if is_workday
                            else None
                        ),
                        clock_in_at=None,
                        clock_out_at=None,
                        record_status="NO_PUNCH",
                        attendance_mode=assignment.attendance_mode,
                        is_absent=False,
                        work_type="REG" if is_workday else "REST",
                        day_type=calendar_day_type(employee_id, work_date),
                        late_minutes=0,
                        undertime_minutes=0,
                        worked_minutes=None,
                        regular_overtime_minutes=0,
                        night_differential_minutes=0,
                        night_differential_overtime_minutes=0,
                        overtime_applications=[],
                        leave_applications=leave_by_employee_date.get(
                            (employee_id, work_date), []
                        ),
                        official_business_requests=official_business_by_employee_date.get(
                            (employee_id, work_date), []
                        ),
                    )
                )
                coverage_inputs.append(
                    (
                        employee_id,
                        report_records[-1],
                        template.required_minutes if is_workday and template else None,
                    )
                )

        _attach_official_business(coverage_inputs, business_requests_by_employee, from_date, to_date)

        if len(report_records) > MAX_REPORT_ROWS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"The report exceeds {MAX_REPORT_ROWS} attendance rows. Narrow the date range or filter by employee number.",
            )
        report_records.sort(key=lambda record: (record.employee_no, record.work_date))
        return ResponseEnvelope(status="success", data=report_records)
