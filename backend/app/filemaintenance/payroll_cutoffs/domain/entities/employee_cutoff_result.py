from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID
from zoneinfo import ZoneInfo

from app.attendance.domain.worked_minutes import (
    ShiftCoverage,
    allocate_official_business_minutes,
    requires_scheduled_work,
    scheduled_work_minutes,
    shift_coverage,
)

PH_TIMEZONE = ZoneInfo("Asia/Manila")
SPECIAL_DAY_TYPES = {"SNW", "SWH", "LOC", "COM"}
HOLIDAY_DAY_TYPES = {"RH", "DBL"}
REGULAR_OVERTIME = "REGULAR_OVERTIME"
NIGHT_DIFFERENTIAL_OVERTIME = "NIGHT_DIFFERENTIAL_OVERTIME"


@dataclass(frozen=True)
class AttendanceFact:
    employee_id: UUID
    work_date: date
    is_absent: bool
    approved_hours_worked: float | None
    approved_night_diff: float | None
    scheduled_minutes: int
    work_type: str
    day_type: str
    late_minutes: int
    undertime_minutes: int
    expected_clock_in_at: datetime | None = None
    expected_clock_out_at: datetime | None = None
    clock_in_at: datetime | None = None
    clock_out_at: datetime | None = None
    schedule_credited: bool = False


@dataclass(frozen=True)
class ScheduledDayFact:
    """A scheduled workday that has no attendance record (e.g. a full-day official business)."""

    employee_id: UUID
    work_date: date
    expected_clock_in_at: datetime
    expected_clock_out_at: datetime
    scheduled_minutes: int
    schedule_credited: bool = False
    work_type: str = "REG"
    day_type: str = "REG"


@dataclass(frozen=True)
class LeaveDayFact:
    leave_date: date
    paid_minutes: int
    unpaid_minutes: int


@dataclass(frozen=True)
class LeaveFact:
    employee_id: UUID
    start_at: datetime
    end_at: datetime
    paid_minutes: int
    unpaid_minutes: int
    days: tuple[LeaveDayFact, ...]
    carry_forward: bool = False


@dataclass(frozen=True)
class OvertimeFact:
    employee_id: UUID
    attendance_date: date
    payable_minutes: int
    overtime_type: str
    work_type: str
    day_type: str


@dataclass(frozen=True)
class OfficialBusinessFact:
    employee_id: UUID
    start_at: datetime
    end_at: datetime
    approved_minutes: int


@dataclass(frozen=True)
class ExceptionFact:
    employee_id: UUID


@dataclass
class EmployeeCutoffTotals:
    employee_id: UUID
    scheduled_dates: set[date] = field(default_factory=set)
    present_dates: set[date] = field(default_factory=set)
    paid_leave_dates: set[date] = field(default_factory=set)
    scheduled_minutes_by_date: dict[date, int] = field(default_factory=dict)
    regular_minutes: int = 0
    late_minutes: int = 0
    undertime_minutes: int = 0
    absence_minutes: int = 0
    paid_leave_minutes: int = 0
    unpaid_leave_minutes: int = 0
    ordinary_ot_minutes: int = 0
    rest_day_minutes: int = 0
    rest_day_ot_minutes: int = 0
    special_day_minutes: int = 0
    special_day_ot_minutes: int = 0
    holiday_minutes: int = 0
    holiday_ot_minutes: int = 0
    night_regular_minutes: int = 0
    night_ot_minutes: int = 0
    official_business_minutes: int = 0
    exception_count: int = 0
    incomplete_time_source_count: int = 0

    @property
    def scheduled_days(self) -> Decimal:
        return Decimal(len(self.scheduled_dates))

    @property
    def required_work_minutes(self) -> int:
        return sum(self.scheduled_minutes_by_date.values())

    @property
    def paid_days(self) -> Decimal:
        return Decimal(len(self.present_dates | self.paid_leave_dates))


@dataclass
class EmployeeCutoffResultEntity:
    cutoff_id: UUID
    employee_id: UUID
    scheduled_days: Decimal
    paid_days: Decimal
    regular_minutes: int
    late_minutes: int
    undertime_minutes: int
    absence_minutes: int
    paid_leave_minutes: int
    unpaid_leave_minutes: int
    ordinary_ot_minutes: int
    rest_day_minutes: int
    rest_day_ot_minutes: int
    special_day_minutes: int
    special_day_ot_minutes: int
    holiday_minutes: int
    holiday_ot_minutes: int
    night_regular_minutes: int
    night_ot_minutes: int
    official_business_minutes: int
    exception_count: int = 0
    employee_confirmation_status: str = "PENDING"
    supervisor_status: str = "PENDING"
    hr_status: str = "PENDING"
    payroll_status: str = "HOLD"
    incomplete_time_source_count: int = 0
    calculated_at: datetime | None = None
    id: UUID | None = None
    employee_name: str | None = None
    cutoff_code: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    operational_group: str | None = None
    attendance_finalized_at: datetime | None = None
    cutoff_locked_at: datetime | None = None


def _hours_to_minutes(hours: float | None) -> int:
    if hours is None:
        return 0
    return int((Decimal(str(hours)) * 60).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def overlap_minutes(
    minutes: int,
    start_at: datetime,
    end_at: datetime,
    cutoff_start: datetime,
    cutoff_end: datetime,
) -> int:
    """Allocate prorated minutes using cumulative rounding to avoid boundary duplicates."""
    interval_seconds = (end_at - start_at).total_seconds()
    if minutes <= 0 or interval_seconds <= 0:
        return 0
    overlap_start = max(start_at, cutoff_start)
    overlap_end = min(end_at, cutoff_end)
    overlap_seconds = (overlap_end - overlap_start).total_seconds()
    if overlap_seconds <= 0:
        return 0
    if overlap_seconds >= interval_seconds:
        return minutes

    def cumulative_minutes(elapsed_seconds: float) -> int:
        ratio = Decimal(str(elapsed_seconds)) / Decimal(str(interval_seconds))
        return int((Decimal(minutes) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    return cumulative_minutes((overlap_end - start_at).total_seconds()) - cumulative_minutes(
        (overlap_start - start_at).total_seconds()
    )


def _add_classified_minutes(
    totals: EmployeeCutoffTotals,
    minutes: int,
    work_type: str,
    day_type: str,
    *,
    overtime: bool = False,
) -> None:
    minutes = max(minutes, 0)
    day_type = day_type.upper()
    work_type = work_type.upper()
    if day_type in HOLIDAY_DAY_TYPES:
        field_name = "holiday_ot_minutes" if overtime else "holiday_minutes"
    elif day_type in SPECIAL_DAY_TYPES:
        field_name = "special_day_ot_minutes" if overtime else "special_day_minutes"
    elif work_type == "REST":
        field_name = "rest_day_ot_minutes" if overtime else "rest_day_minutes"
    else:
        field_name = "ordinary_ot_minutes" if overtime else "regular_minutes"
    setattr(totals, field_name, getattr(totals, field_name) + minutes)


def _subtract_classified_minutes(
    totals: EmployeeCutoffTotals,
    minutes: int,
    work_type: str,
    day_type: str,
) -> None:
    minutes = max(minutes, 0)
    day_type = day_type.upper()
    work_type = work_type.upper()
    if day_type in HOLIDAY_DAY_TYPES:
        field_name = "holiday_minutes"
    elif day_type in SPECIAL_DAY_TYPES:
        field_name = "special_day_minutes"
    elif work_type == "REST":
        field_name = "rest_day_minutes"
    else:
        field_name = "regular_minutes"
    setattr(totals, field_name, max(0, getattr(totals, field_name) - minutes))


def calculate_employee_cutoff_totals(
    employee_ids: list[UUID],
    attendance: list[AttendanceFact],
    leaves: list[LeaveFact],
    overtime: list[OvertimeFact],
    official_business: list[OfficialBusinessFact],
    exceptions: list[ExceptionFact],
    period_start: date,
    period_end: date,
    scheduled_days: list[ScheduledDayFact] | None = None,
) -> list[EmployeeCutoffTotals]:
    """Aggregate source facts into the payroll.employee_cutoff_results time fields."""
    cutoff_start = datetime.combine(period_start, time.min, tzinfo=PH_TIMEZONE)
    cutoff_end = datetime.combine(
        period_end + timedelta(days=1),
        time.min,
        tzinfo=PH_TIMEZONE,
    )
    totals = {employee_id: EmployeeCutoffTotals(employee_id=employee_id) for employee_id in employee_ids}
    shifts_by_employee: dict[UUID, list[ShiftCoverage]] = {}
    leave_minutes_by_date: dict[tuple[UUID, date], int] = {}
    for leave in leaves:
        for day in leave.days:
            if leave.carry_forward or period_start <= day.leave_date <= period_end:
                key = (leave.employee_id, day.leave_date)
                leave_minutes_by_date[key] = leave_minutes_by_date.get(key, 0) + max(
                    day.paid_minutes, 0
                ) + max(day.unpaid_minutes, 0)
    schedule_credited_minutes_by_date: dict[
        tuple[UUID, date], tuple[int, str, str]
    ] = {}
    for record in attendance:
        current = totals.get(record.employee_id)
        if current is None:
            continue
        requires_work = requires_scheduled_work(record.work_type, record.day_type)
        worked_minutes = 0
        if requires_work:
            current.scheduled_dates.add(record.work_date)
            current.scheduled_minutes_by_date[record.work_date] = max(
                current.scheduled_minutes_by_date.get(record.work_date, 0),
                max(record.scheduled_minutes, 0),
            )
        schedule_credit_key = (record.employee_id, record.work_date)
        if record.schedule_credited and requires_work and not record.is_absent:
            leave_minutes = min(
                max(record.scheduled_minutes, 0),
                leave_minutes_by_date.get(schedule_credit_key, 0),
            )
            worked_minutes = max(record.scheduled_minutes - leave_minutes, 0)
            schedule_credited_minutes_by_date[schedule_credit_key] = (
                worked_minutes,
                record.work_type,
                record.day_type,
            )
            if worked_minutes > 0:
                _add_classified_minutes(current, worked_minutes, record.work_type, record.day_type)
            if record.late_minutes == 0 and record.undertime_minutes == 0 and worked_minutes > 0:
                current.present_dates.add(record.work_date)
        elif record.is_absent:
            if requires_work:
                current.absence_minutes += max(record.scheduled_minutes, 0)
        else:
            current.present_dates.add(record.work_date)
            if record.approved_hours_worked is None:
                current.incomplete_time_source_count += 1
            if record.approved_hours_worked is None:
                worked_minutes = 0
            elif requires_work:
                worked_minutes = scheduled_work_minutes(
                    record.scheduled_minutes,
                    record.late_minutes,
                    record.undertime_minutes,
                    record.work_type,
                    record.day_type,
                ) or 0
            else:
                worked_minutes = max(_hours_to_minutes(record.approved_hours_worked), 0)
            _add_classified_minutes(current, worked_minutes, record.work_type, record.day_type)
            night_minutes = max(_hours_to_minutes(record.approved_night_diff), 0)
            current.night_regular_minutes += (
                min(night_minutes, worked_minutes) if requires_work else night_minutes
            )
        if not record.schedule_credited:
            current.late_minutes += max(record.late_minutes, 0)
            current.undertime_minutes += max(record.undertime_minutes, 0)
        coverage = shift_coverage(
            work_date=record.work_date,
            expected_clock_in_at=record.expected_clock_in_at,
            expected_clock_out_at=record.expected_clock_out_at,
            required_minutes=record.scheduled_minutes,
            credited_work_minutes=(
                min(
                    max(record.scheduled_minutes, 0),
                    leave_minutes_by_date.get(schedule_credit_key, 0),
                )
                if record.schedule_credited and not record.is_absent
                else worked_minutes
            ),
            work_type=record.work_type,
            day_type=record.day_type,
            clock_in_at=(
                None
                if record.is_absent or record.schedule_credited
                else record.clock_in_at
            ),
            clock_out_at=(
                None
                if record.is_absent or record.schedule_credited
                else record.clock_out_at
            ),
        )
        if coverage is not None:
            shifts_by_employee.setdefault(record.employee_id, []).append(coverage)

    unrecorded_minutes: dict[tuple[UUID, date], int] = {}
    for day in scheduled_days or []:
        if day.employee_id not in totals or not period_start <= day.work_date <= period_end:
            continue
        if not requires_scheduled_work(day.work_type, day.day_type):
            continue
        coverage = shift_coverage(
            work_date=day.work_date,
            expected_clock_in_at=day.expected_clock_in_at,
            expected_clock_out_at=day.expected_clock_out_at,
            required_minutes=day.scheduled_minutes,
            work_type=day.work_type,
            day_type=day.day_type,
            credited_work_minutes=(
                min(
                    max(day.scheduled_minutes, 0),
                    leave_minutes_by_date.get((day.employee_id, day.work_date), 0),
                )
                if day.schedule_credited
                else 0
            ),
        )
        if coverage is not None:
            shifts_by_employee.setdefault(day.employee_id, []).append(coverage)
            unrecorded_minutes[(day.employee_id, day.work_date)] = max(day.scheduled_minutes, 0)
        if day.schedule_credited:
            current = totals[day.employee_id]
            current.scheduled_dates.add(day.work_date)
            current.scheduled_minutes_by_date[day.work_date] = max(
                current.scheduled_minutes_by_date.get(day.work_date, 0),
                max(day.scheduled_minutes, 0),
            )
            leave_minutes = min(
                max(day.scheduled_minutes, 0),
                leave_minutes_by_date.get((day.employee_id, day.work_date), 0),
            )
            credited_minutes = max(day.scheduled_minutes - leave_minutes, 0)
            schedule_credited_minutes_by_date[(day.employee_id, day.work_date)] = (
                credited_minutes,
                day.work_type,
                day.day_type,
            )
            if credited_minutes > 0:
                _add_classified_minutes(
                    current,
                    credited_minutes,
                    day.work_type,
                    day.day_type,
                )

    for leave in leaves:
        current = totals.get(leave.employee_id)
        if current is None:
            continue
        if leave.days:
            included_days = [
                day
                for day in leave.days
                if leave.carry_forward or period_start <= day.leave_date <= period_end
            ]
            paid = sum(day.paid_minutes for day in included_days)
            unpaid = sum(day.unpaid_minutes for day in included_days)
            current.paid_leave_dates.update(day.leave_date for day in included_days if day.paid_minutes > 0)
        elif leave.carry_forward:
            paid = leave.paid_minutes
            unpaid = leave.unpaid_minutes
            local_start = leave.start_at.astimezone(PH_TIMEZONE).date()
            local_end = leave.end_at.astimezone(PH_TIMEZONE).date()
            current.paid_leave_dates.update(
                day
                for day in (
                    local_start + timedelta(days=index)
                    for index in range((local_end - local_start).days + 1)
                )
                if paid > 0
            )
        else:
            paid = overlap_minutes(leave.paid_minutes, leave.start_at, leave.end_at, cutoff_start, cutoff_end)
            unpaid = overlap_minutes(leave.unpaid_minutes, leave.start_at, leave.end_at, cutoff_start, cutoff_end)
            local_start = leave.start_at.astimezone(PH_TIMEZONE).date()
            local_end = leave.end_at.astimezone(PH_TIMEZONE).date()
            current.paid_leave_dates.update(
                day
                for day in (local_start + timedelta(days=index) for index in range((local_end - local_start).days + 1))
                if period_start <= day <= period_end and paid > 0
            )
        current.paid_leave_minutes += max(paid, 0)
        current.unpaid_leave_minutes += max(unpaid, 0)

    for request in overtime:
        current = totals.get(request.employee_id)
        if current is None or not period_start <= request.attendance_date <= period_end:
            continue
        minutes = max(request.payable_minutes, 0)
        if request.overtime_type == NIGHT_DIFFERENTIAL_OVERTIME:
            current.night_ot_minutes += minutes
        elif request.overtime_type == REGULAR_OVERTIME:
            _add_classified_minutes(
                current,
                minutes,
                request.work_type,
                request.day_type,
                overtime=True,
            )

    used_by_employee: dict[UUID, dict[date, int]] = {}
    for request in sorted(official_business, key=lambda item: item.start_at):
        current = totals.get(request.employee_id)
        if current is None:
            continue
        allocation = allocate_official_business_minutes(
            request.start_at,
            request.end_at,
            request.approved_minutes,
            shifts_by_employee.get(request.employee_id, []),
            used_by_employee.setdefault(request.employee_id, {}),
        )
        current.official_business_minutes += sum(allocation.values())
        for work_date in allocation:
            credited_schedule = schedule_credited_minutes_by_date.get(
                (request.employee_id, work_date)
            )
            if credited_schedule is not None:
                credited_work_minutes, work_type, day_type = credited_schedule
                credited_ob_minutes = allocation[work_date]
                _subtract_classified_minutes(
                    current,
                    credited_ob_minutes,
                    work_type,
                    day_type,
                )
                schedule_credited_minutes_by_date[(request.employee_id, work_date)] = (
                    max(0, credited_work_minutes - credited_ob_minutes),
                    work_type,
                    day_type,
                )
                if credited_work_minutes > 0 or credited_ob_minutes > 0:
                    current.present_dates.add(work_date)
            scheduled_minutes = unrecorded_minutes.get((request.employee_id, work_date))
            if scheduled_minutes is not None:
                # A scheduled day without punches still requires its schedule.
                current.scheduled_dates.add(work_date)
                current.scheduled_minutes_by_date[work_date] = scheduled_minutes

    for exception in exceptions:
        current = totals.get(exception.employee_id)
        if current is not None:
            current.exception_count += 1

    return [totals[employee_id] for employee_id in sorted(totals, key=str)]
