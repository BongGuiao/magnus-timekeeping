from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, exists, or_, select

from app.attendance.domain.worked_minutes import (
    allocate_official_business_minutes,
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
    get_current_authorization_use_case,
    require_any_permission,
)
from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
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
        coverage = shift_coverage(
            work_date=record.work_date,
            expected_clock_in_at=record.expected_clock_in_at,
            expected_clock_out_at=record.expected_clock_out_at,
            required_minutes=required_minutes,
            credited_work_minutes=0 if record.is_absent else record.worked_minutes or 0,
            work_type=record.work_type,
            day_type=record.day_type,
            clock_in_at=None if record.is_absent else record.clock_in_at,
            clock_out_at=None if record.is_absent else record.clock_out_at,
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
    "/attendance-detail",
    response_model=ResponseEnvelope[list[AttendanceDetailReportRecord]],
)
async def get_attendance_detail_report(
    from_date: date = Query(...),
    to_date: date = Query(...),
    scope: str = Query(..., pattern="^(own|team|organization)$"),
    employee_no: str | None = Query(default=None, min_length=1, max_length=30),
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
                select(EmploymentAssignmentModel, LocationModel.province, LocationModel.city)
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
                    EmploymentAssignmentModel.effective_from <= to_date,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= from_date,
                    ),
                )
                .order_by(EmploymentAssignmentModel.effective_from.desc())
            )
        ).all() if employee_ids else []
        employment_by_employee: dict[UUID, list[tuple[EmploymentAssignmentModel, str | None, str | None]]] = {}
        company_ids: set[UUID] = set()
        for employment, province, city in employment_rows:
            employment_by_employee.setdefault(employment.employee_id, []).append(
                (employment, province, city)
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
                for employment, _, _ in employment_by_employee.get(employee_id, [])
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
                    (province, city)
                    for candidate, province, city in employment_by_employee[employee_id]
                    if candidate.id == employment.id
                ),
                (None, None),
            )

            def scope_matches(calendar_value: str | None, location_value: str | None) -> bool:
                return not calendar_value or (
                    location_value is not None
                    and calendar_value.strip().casefold()
                    == location_value.strip().casefold()
                )

            priorities = ("DBL", "RH", "SNW", "LOC", "COM", "SWH")
            matches: list[str] = []
            for holiday, calendar in holidays_by_date.get(work_date, []):
                if calendar.company_id != employment.company_id:
                    continue
                if calendar.effective_year != work_date.year:
                    continue
                if not (
                    scope_matches(calendar.province, location[0])
                    and scope_matches(calendar.city, location[1])
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
                    is_absent=attendance.is_absent,
                    work_type=attendance.work_type,
                    day_type=attendance.day_type,
                    late_minutes=attendance.late_minutes,
                    undertime_minutes=attendance.undertime_minutes,
                    worked_minutes=_worked_minutes(attendance, required_minutes),
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
