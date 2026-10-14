from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID
from zoneinfo import ZoneInfo

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

    @property
    def scheduled_days(self) -> Decimal:
        return Decimal(len(self.scheduled_dates))

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
    calculated_at: datetime | None = None
    id: UUID | None = None
    employee_name: str | None = None
    cutoff_code: str | None = None
    period_start: date | None = None
    period_end: date | None = None


def _hours_to_minutes(hours: float | None) -> int:
    if hours is None:
        return 0
    return int((Decimal(str(hours)) * 60).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _overlap_minutes(
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


def calculate_employee_cutoff_totals(
    employee_ids: list[UUID],
    attendance: list[AttendanceFact],
    leaves: list[LeaveFact],
    overtime: list[OvertimeFact],
    official_business: list[OfficialBusinessFact],
    exceptions: list[ExceptionFact],
    period_start: date,
    period_end: date,
) -> list[EmployeeCutoffTotals]:
    """Aggregate source facts into the payroll.employee_cutoff_results time fields."""
    cutoff_start = datetime.combine(period_start, time.min, tzinfo=PH_TIMEZONE)
    cutoff_end = datetime.combine(
        period_end + timedelta(days=1),
        time.min,
        tzinfo=PH_TIMEZONE,
    )
    totals = {employee_id: EmployeeCutoffTotals(employee_id=employee_id) for employee_id in employee_ids}
    for record in attendance:
        current = totals.get(record.employee_id)
        if current is None:
            continue
        current.scheduled_dates.add(record.work_date)
        if record.is_absent:
            current.absence_minutes += max(record.scheduled_minutes, 0)
        else:
            current.present_dates.add(record.work_date)
            worked_minutes = max(_hours_to_minutes(record.approved_hours_worked), 0)
            _add_classified_minutes(current, worked_minutes, record.work_type, record.day_type)
            current.night_regular_minutes += max(_hours_to_minutes(record.approved_night_diff), 0)
        current.late_minutes += max(record.late_minutes, 0)
        current.undertime_minutes += max(record.undertime_minutes, 0)

    for leave in leaves:
        current = totals.get(leave.employee_id)
        if current is None:
            continue
        if leave.days:
            included_days = [day for day in leave.days if period_start <= day.leave_date <= period_end]
            paid = sum(day.paid_minutes for day in included_days)
            unpaid = sum(day.unpaid_minutes for day in included_days)
            current.paid_leave_dates.update(day.leave_date for day in included_days if day.paid_minutes > 0)
        else:
            paid = _overlap_minutes(leave.paid_minutes, leave.start_at, leave.end_at, cutoff_start, cutoff_end)
            unpaid = _overlap_minutes(leave.unpaid_minutes, leave.start_at, leave.end_at, cutoff_start, cutoff_end)
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

    for request in official_business:
        current = totals.get(request.employee_id)
        if current is None:
            continue
        current.official_business_minutes += max(
            _overlap_minutes(
                request.approved_minutes,
                request.start_at,
                request.end_at,
                cutoff_start,
                cutoff_end,
            ),
            0,
        )

    for exception in exceptions:
        current = totals.get(exception.employee_id)
        if current is not None:
            current.exception_count += 1

    return [totals[employee_id] for employee_id in sorted(totals, key=str)]
