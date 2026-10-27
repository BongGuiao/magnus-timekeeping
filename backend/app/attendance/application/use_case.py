from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal
import logging
from math import isfinite
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional
from uuid import UUID

from geoalchemy2 import Geography, Geometry
from sqlalchemy import and_, case, cast, or_, select, func, false
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.attendance.domain.entities.attendance import AttendanceEntity
from app.attendance.infrastructure.db_model import AttendanceModel
from app.attendance.infrastructure.punch_exceptions import PunchRuleViolation
from app.auth.application.accounts import employee_display_name
from app.auth.domain.entities.user import AccountStatus, UserEntity
from app.auth.infrastructure.db_model import UserModel
from app.enrollment.domain.entities.enrollment import EnrollmentStatus, FaceEnrollmentEntity
from app.enrollment.infrastructure.db_model import FaceEnrollmentModel
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentGeofenceModel,
    EmploymentAssignmentModel,
    EmployeeWfhLocationModel,
)
from app.filemaintenance.geofences.infrastructure.db_model import Geofence
from app.filemaintenance.location.infrastructure.db_model import Location as LocationModel
from app.filemaintenance.schedule.infrastructure.db_model import (
    EmployeeScheduleAssignmentModel,
    RestDayPatternDayModel,
    RestDayPatternModel,
    ScheduleSegmentModel,
    ScheduleTemplateModel,
)
from app.filemaintenance.schedule.infrastructure.emergency_schedule_db_model import (
    EmergencyScheduleRequestModel,
)
from app.filemaintenance.holidays.calendar.infrastructure.db_model import HolidayCalendarModel
from app.filemaintenance.holidays.calendar.domain.scope import (
    GeographicArea,
    holiday_applies_to_location,
)
from app.filemaintenance.holidays.holiday.infrastructure.db_model import HolidayModel


# attendance.day_type is String(10), so holiday types are stored as short codes.
HOLIDAY_DAY_TYPES = {
    "REGULAR": "RH",
    "SPECIAL_NONWORKING": "SNW",
    "SPECIAL_WORKING": "SWH",
    "LOCAL": "LOC",
    "COMPANY": "COM",
}
HOLIDAY_DAY_TYPE_PRIORITY = ("DBL", "RH", "SNW", "LOC", "COM", "SWH")

PH_TIMEZONE = ZoneInfo("Asia/Manila")
logger = logging.getLogger(__name__)

DEFAULT_EXPECTED_CLOCK_IN = time(9, 0)
DEFAULT_EXPECTED_CLOCK_OUT = time(18, 0)
MAX_OPEN_ATTENDANCE_AGE = timedelta(hours=24)
MAX_FACE_MATCH_CANDIDATES = 10000


def circle_contains_gps(
    center: ColumnElement,
    point: ColumnElement,
    radius: ColumnElement | Decimal,
    accuracy_meters: float,
) -> ColumnElement[bool]:
    return func.ST_DWithin(center, point, radius - accuracy_meters)


def to_ph_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(PH_TIMEZONE).isoformat()


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def validate_early_clock_in(
    actual_clock_in_at: datetime,
    expected_clock_in_at: datetime,
    allowance_minutes: int,
) -> None:
    if allowance_minutes < 0:
        raise ValueError("Early clock-in allowance cannot be negative.")
    earliest = to_utc(expected_clock_in_at) - timedelta(minutes=allowance_minutes)
    if to_utc(actual_clock_in_at) < earliest:
        local_earliest = earliest.astimezone(PH_TIMEZONE)
        raise PunchRuleViolation(
            f"Clock-in is too early. You may clock in starting "
            f"{local_earliest:%Y-%m-%d %I:%M %p} Philippine time "
            f"({allowance_minutes} minute(s) before your scheduled start).",
            "CLOCK_IN_TOO_EARLY",
            {
                "scheduled_start_at": expected_clock_in_at.isoformat(),
                "earliest_clock_in_at": earliest.isoformat(),
                "allowance_minutes": allowance_minutes,
            },
        )


BREAK_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("first_break_out_at", "first_break_in_at", "first break"),
    ("meal_break_out_at", "meal_break_in_at", "meal break"),
    ("second_break_out_at", "second_break_in_at", "second break"),
    ("ot_break_out_at", "ot_break_in_at", "overtime break"),
)
UNPAID_BREAK_PAIRS = (
    ("meal_break_out_at", "meal_break_in_at"),
)
BREAK_SLOT_FIELDS = {
    "FIRST_BREAK": ("first_break_out_at", "first_break_in_at"),
    "MEAL_BREAK": ("meal_break_out_at", "meal_break_in_at"),
    "SECOND_BREAK": ("second_break_out_at", "second_break_in_at"),
    "OT_BREAK": ("ot_break_out_at", "ot_break_in_at"),
}
PUNCH_FIELDS: tuple[str, ...] = ("clock_in_at", "clock_out_at") + tuple(
    field for start, end, _ in BREAK_PAIRS for field in (start, end)
)


def get_active_break(record: AttendanceEntity) -> str | None:
    for start_field, end_field, label in BREAK_PAIRS:
        if getattr(record, start_field) is not None and getattr(record, end_field) is None:
            return label
    return None


def get_unpaid_break_intervals(
    record: AttendanceEntity,
) -> tuple[tuple[datetime | None, datetime | None], ...]:
    return tuple(
        (getattr(record, start_field), getattr(record, end_field))
        for start_field, end_field in UNPAID_BREAK_PAIRS
    )


def calculate_break_policy(
    record: AttendanceEntity,
    rules: list[dict[str, Any]],
    *,
    require_complete: bool = True,
) -> tuple[int, int, tuple[tuple[datetime | None, datetime | None], ...]]:
    excess_minutes = 0
    unpaid_minutes = 0
    deducted_intervals: list[tuple[datetime | None, datetime | None]] = []
    configured_starts = set()
    if (
        (record.ot_break_out_at is not None or record.ot_break_in_at is not None)
        and not any(rule.get("break_slot") == "OT_BREAK" for rule in rules)
    ):
        raise ValueError("Configure a paid OT_BREAK allowance in the employee's schedule template.")
    for rule in rules:
        break_slot = rule["break_slot"]
        start_field, end_field = BREAK_SLOT_FIELDS[break_slot]
        configured_starts.add(start_field)
        start = getattr(record, start_field)
        end = getattr(record, end_field)
        allowance = rule["break_minutes"]
        is_paid_break = (
            break_slot in ("FIRST_BREAK", "SECOND_BREAK", "OT_BREAK")
            or rule["segment_type"] == "PAID_BREAK"
        )
        if start is None and end is None:
            if not is_paid_break:
                if rule["auto_deduct"]:
                    unpaid_minutes += allowance
                elif require_complete and break_slot != "FIRST_BREAK":
                    raise ValueError(f"Complete the required {rule['break_slot'].lower().replace('_', ' ')} punches before clocking out.")
            continue
        if start is None or end is None or to_utc(end) <= to_utc(start):
            raise ValueError("Break punches must form a valid completed interval.")
        duration = int((to_utc(end) - to_utc(start)).total_seconds() // 60)
        excess_minutes += max(0, duration - allowance)
        if not is_paid_break:
            unpaid_minutes += max(
                duration,
                allowance if break_slot == "MEAL_BREAK" else 0,
            )
            deducted_intervals.append((start, end))
        else:
            excess_start = to_utc(start) + timedelta(minutes=allowance)
            if excess_start < to_utc(end):
                deducted_intervals.append((excess_start, end))
    for start_field, end_field in UNPAID_BREAK_PAIRS:
        if start_field not in configured_starts:
            start = getattr(record, start_field)
            end = getattr(record, end_field)
            if start is None and end is None:
                continue
            if start is None or end is None or to_utc(end) <= to_utc(start):
                raise ValueError("Break punches must form a valid completed interval.")
            unpaid_minutes += int((to_utc(end) - to_utc(start)).total_seconds() // 60)
            deducted_intervals.append((start, end))
    return excess_minutes, unpaid_minutes, tuple(deducted_intervals)


def calculate_net_nonpayable_break_minutes(
    record: Any,
    rules: list[dict[str, Any]],
    break_intervals: tuple[tuple[datetime | None, datetime | None], ...],
    actual_clock_in_at: datetime | None,
    actual_clock_out_at: datetime | None,
) -> int:
    if (
        actual_clock_in_at is None
        or actual_clock_out_at is None
        or to_utc(actual_clock_out_at) <= to_utc(actual_clock_in_at)
    ):
        return 0

    start_at = to_utc(actual_clock_in_at)
    end_at = to_utc(actual_clock_out_at)
    gross_seconds = (end_at - start_at).total_seconds()
    deducted_seconds = gross_seconds - _net_interval_seconds(
        start_at,
        end_at,
        break_intervals,
    )
    meal_break_deduction_top_up = 0
    for rule in rules:
        if rule["break_slot"] != "MEAL_BREAK" or rule["segment_type"] != "UNPAID_BREAK":
            continue
        start_field, end_field = BREAK_SLOT_FIELDS["MEAL_BREAK"]
        meal_start = getattr(record, start_field)
        meal_end = getattr(record, end_field)
        if meal_start is None or meal_end is None:
            continue
        meal_duration = int(
            (to_utc(meal_end) - to_utc(meal_start)).total_seconds() // 60
        )
        meal_break_deduction_top_up += max(
            0,
            int(rule["break_minutes"]) - meal_duration,
        )
    auto_deduct_minutes = sum(
        int(rule["break_minutes"])
        for rule in rules
        if rule["break_slot"] == "MEAL_BREAK"
        and rule["segment_type"] == "UNPAID_BREAK"
        and rule["auto_deduct"]
        and getattr(record, BREAK_SLOT_FIELDS[rule["break_slot"]][0]) is None
    )
    return min(
        int(gross_seconds // 60),
        int(deducted_seconds // 60)
        + meal_break_deduction_top_up
        + auto_deduct_minutes,
    )


async def resolve_record_break_rules(
    uow: GenUnitOfWork,
    record: AttendanceEntity,
) -> list[dict[str, Any]]:
    rules = (record.punch_metadata or {}).get("schedule_context", {}).get("break_rules", [])
    if rules or not record.schedule_template_id or not record.work_date:
        return rules

    segments = list((await uow.session.scalars(
        select(ScheduleSegmentModel).where(
            ScheduleSegmentModel.schedule_template_id == record.schedule_template_id,
            ScheduleSegmentModel.break_slot.is_not(None),
        ).order_by(ScheduleSegmentModel.segment_sequence)
    )).all())

    return [
        {
            "segment_id": str(segment.id),
            "break_slot": segment.break_slot,
            "segment_type": segment.segment_type,
            "break_minutes": segment.break_minutes,
            "auto_deduct": segment.auto_deduct,
            "start_at": datetime.combine(record.work_date, segment.start_time, tzinfo=PH_TIMEZONE).isoformat(),
            "end_at": datetime.combine(
                record.work_date + timedelta(days=segment.end_day_offset),
                segment.end_time,
                tzinfo=PH_TIMEZONE,
            ).isoformat(),
        }
        for segment in segments
    ]


def get_last_punch_time(record: AttendanceEntity) -> datetime | None:
    punches = [to_utc(value) for field in PUNCH_FIELDS if (value := getattr(record, field)) is not None]
    return max(punches) if punches else None


def get_cycle_day_number(effective_from: date, work_date: date, cycle_length_days: int) -> int:
    if cycle_length_days < 1:
        raise ValueError("Rest-day pattern cycle length must be at least one day.")
    if work_date < effective_from:
        raise ValueError("Attendance work date cannot precede the schedule assignment.")
    if cycle_length_days == 7:
        # Weekly patterns follow the calendar week: Day 1 = Monday ... Day 7 = Sunday.
        return work_date.weekday() + 1
    return ((work_date - effective_from).days % cycle_length_days) + 1


def calculate_attendance_metrics(
    *,
    expected_clock_in_at: datetime | None,
    expected_clock_out_at: datetime | None,
    actual_clock_in_at: datetime | None,
    actual_clock_out_at: datetime | None,
    grace_minutes: int = 0,
    ot_eligible: bool = False,
    minimum_ot_minutes: int = 0,
    pre_shift_ot_allowed: bool = False,
    break_intervals: tuple[tuple[datetime | None, datetime | None], ...] = (),
) -> tuple[int, int, int]:
    late_minutes = 0
    if expected_clock_in_at is not None and actual_clock_in_at is not None:
        latest_on_time = to_utc(expected_clock_in_at) + timedelta(minutes=max(0, grace_minutes))
        actual_clock_in = to_utc(actual_clock_in_at)
        if actual_clock_in > latest_on_time:
            late_minutes = int((actual_clock_in - latest_on_time).total_seconds() // 60)

    undertime_minutes = 0
    if expected_clock_out_at is not None and actual_clock_out_at is not None:
        expected_clock_out = to_utc(expected_clock_out_at)
        actual_clock_out = to_utc(actual_clock_out_at)
        if actual_clock_out < expected_clock_out:
            undertime_minutes = int((expected_clock_out - actual_clock_out).total_seconds() // 60)

    _, _, overtime_minutes = calculate_overtime_breakdown(
        expected_clock_in_at=expected_clock_in_at,
        expected_clock_out_at=expected_clock_out_at,
        actual_clock_in_at=actual_clock_in_at,
        actual_clock_out_at=actual_clock_out_at,
        ot_eligible=ot_eligible,
        minimum_ot_minutes=minimum_ot_minutes,
        pre_shift_ot_allowed=pre_shift_ot_allowed,
        break_intervals=break_intervals,
    )

    return late_minutes, undertime_minutes, overtime_minutes


def calculate_overtime_breakdown(
    *,
    expected_clock_in_at: datetime | None,
    expected_clock_out_at: datetime | None,
    actual_clock_in_at: datetime | None,
    actual_clock_out_at: datetime | None,
    ot_eligible: bool = False,
    minimum_ot_minutes: int = 0,
    pre_shift_ot_allowed: bool = False,
    break_intervals: tuple[tuple[datetime | None, datetime | None], ...] = (),
) -> tuple[int, int, int]:
    if not ot_eligible or expected_clock_out_at is None or actual_clock_out_at is None:
        return 0, 0, 0

    expected_clock_out = to_utc(expected_clock_out_at)
    actual_clock_out = to_utc(actual_clock_out_at)
    overtime_intervals: list[tuple[datetime, datetime]] = []
    if actual_clock_out > expected_clock_out:
        overtime_intervals.append((expected_clock_out, actual_clock_out))
    if (
        pre_shift_ot_allowed
        and expected_clock_in_at is not None
        and actual_clock_in_at is not None
    ):
        expected_clock_in = to_utc(expected_clock_in_at)
        actual_clock_in = to_utc(actual_clock_in_at)
        if actual_clock_in < expected_clock_in:
            overtime_intervals.append((actual_clock_in, expected_clock_in))

    total_seconds = sum(
        _net_interval_seconds(start, end, break_intervals)
        for start, end in overtime_intervals
    )
    night_seconds = sum(
        _night_overlap_seconds(start, end, break_intervals)
        for start, end in overtime_intervals
    )
    total_minutes = int(total_seconds // 60)
    if total_minutes < max(0, minimum_ot_minutes):
        return 0, 0, 0

    night_minutes = min(total_minutes, int(night_seconds // 60))
    regular_minutes = total_minutes - night_minutes
    return regular_minutes, night_minutes, total_minutes


def _net_interval_seconds(
    start_at: datetime,
    end_at: datetime,
    break_intervals: tuple[tuple[datetime | None, datetime | None], ...],
) -> float:
    intervals = []
    for break_start, break_end in break_intervals:
        if break_start is None or break_end is None:
            continue
        clipped_start = max(start_at, to_utc(break_start))
        clipped_end = min(end_at, to_utc(break_end))
        if clipped_start < clipped_end:
            intervals.append((clipped_start, clipped_end))
    intervals.sort()

    break_seconds = 0.0
    merged_start = None
    merged_end = None
    for start, end in intervals:
        if merged_end is None:
            merged_start, merged_end = start, end
        elif start <= merged_end:
            merged_end = max(merged_end, end)
        else:
            break_seconds += (merged_end - merged_start).total_seconds()
            merged_start, merged_end = start, end
    if merged_end is not None and merged_start is not None:
        break_seconds += (merged_end - merged_start).total_seconds()
    return max(0.0, (end_at - start_at).total_seconds() - break_seconds)


def _night_overlap_seconds(
    start_at: datetime,
    end_at: datetime,
    break_intervals: tuple[tuple[datetime | None, datetime | None], ...],
) -> float:
    local_timezone = ZoneInfo("Asia/Manila")
    first_date = start_at.astimezone(local_timezone).date() - timedelta(days=1)
    last_date = end_at.astimezone(local_timezone).date()
    night_seconds = 0.0
    current_date = first_date
    while current_date <= last_date:
        night_start = to_utc(
            datetime.combine(current_date, time(hour=22), tzinfo=local_timezone)
        )
        night_end = to_utc(
            datetime.combine(
                current_date + timedelta(days=1),
                time(hour=6),
                tzinfo=local_timezone,
            )
        )
        clipped_start = max(start_at, night_start)
        clipped_end = min(end_at, night_end)
        if clipped_start < clipped_end:
            night_seconds += _net_interval_seconds(
                clipped_start,
                clipped_end,
                break_intervals,
            )
        current_date += timedelta(days=1)
    return night_seconds


def calculate_night_differential_minutes(
    *,
    actual_clock_in_at: datetime | None,
    actual_clock_out_at: datetime | None,
    break_intervals: tuple[tuple[datetime | None, datetime | None], ...] = (),
) -> int:
    if actual_clock_in_at is None or actual_clock_out_at is None:
        return 0

    start_at = to_utc(actual_clock_in_at)
    end_at = to_utc(actual_clock_out_at)
    if end_at <= start_at:
        return 0

    worked_seconds = _night_overlap_seconds(start_at, end_at, break_intervals)
    return int(worked_seconds // 60)


@dataclass(frozen=True)
class ScheduleDayConfiguration:
    work_type: str
    expected_clock_in_at: datetime | None
    expected_clock_out_at: datetime | None
    schedule_template_id: UUID | None = None
    grace_minutes: int = 0
    ot_eligible: bool = False
    minimum_ot_minutes: int = 0
    pre_shift_ot_allowed: bool = False
    schedule_context: dict[str, Any] | None = None
    early_clock_in_allowance_minutes: int = 0


@dataclass(frozen=True)
class ClockAttendanceInputDTO:
    image_bytes: bytes
    user_id: UUID
    clock_out_confirmed: bool = False
    device_approved: bool = True
    enforce_geofence: bool = False
    clock_channel: Optional[Dict[str, Any]] = None
    punch_metadata: Optional[Dict[str, Any]] = None  # E.g., {"lat": 15.1, "lng": 120.5, "device": "Kiosk"}
    latitude: float | None = None
    longitude: float | None = None
    gps_accuracy_meters: float | None = None
    allow_wfh: bool = False


@dataclass(frozen=True)
class ClockAttendanceOutputDTO:
    employee_name: str
    employee_code: str
    action: str  # "clock_in" | "clock_out"
    timestamp: str
    schedule_template_id: UUID | None = None
    approval_required: bool = False
    punch_metadata: Optional[Dict[str, Any]] = None  # E.g., {"lat": 15.1, "lng": 120.5, "device": "Kiosk"}
    late_minutes: int = 0
    undertime_minutes: int = 0
    calculated_ot_minutes: int = 0
    overtime_hours: float = 0
    regular_overtime_minutes: int = 0
    regular_overtime_hours: float = 0
    night_differential_overtime_minutes: int = 0
    night_differential_overtime_hours: float = 0
    night_differential_hours: float = 0


@dataclass(frozen=True)
class GetLastAttendanceInputDTO:
    user_id: UUID


@dataclass(frozen=True)
class LastAttendanceOutputDTO:
    work_date: str
    schedule_template_id: UUID | None
    clock_in_at: Optional[str]
    clock_out_at: Optional[str]
    first_break_out_at: Optional[str]
    first_break_in_at: Optional[str]
    second_break_out_at: Optional[str]
    second_break_in_at: Optional[str]
    meal_break_out_at: Optional[str]
    meal_break_in_at: Optional[str]
    ot_break_out_at: Optional[str]
    ot_break_in_at: Optional[str]
    expected_clock_in_at: Optional[str]
    expected_clock_out_at: Optional[str]
    break_rules: list[dict[str, Any]] = field(default_factory=list)


class GetLastAttendanceUseCase(BaseUseCase[Optional[LastAttendanceOutputDTO]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, input_dto: GetLastAttendanceInputDTO) -> Optional[LastAttendanceOutputDTO]:
        async with self.uow as uow:
            repo = uow.get_repo(AttendanceEntity, AttendanceModel)
            records = await repo.find_all(
                AttendanceModel.user_id == input_dto.user_id,
                order_by=[AttendanceModel.work_date.desc(), AttendanceModel.clock_in_at.desc()],
                limit=1,
            )

            if not records:
                return None

            last = records[0]
            break_rules = await resolve_record_break_rules(uow, last)
            return LastAttendanceOutputDTO(
                work_date=last.work_date.isoformat(),
                schedule_template_id=last.schedule_template_id,
                clock_in_at=to_ph_iso(last.clock_in_at),
                clock_out_at=to_ph_iso(last.clock_out_at),
                first_break_out_at=to_ph_iso(last.first_break_out_at),
                first_break_in_at=to_ph_iso(last.first_break_in_at),
                second_break_out_at=to_ph_iso(last.second_break_out_at),
                second_break_in_at=to_ph_iso(last.second_break_in_at),
                meal_break_out_at=to_ph_iso(last.meal_break_out_at),
                meal_break_in_at=to_ph_iso(last.meal_break_in_at),
                ot_break_out_at=to_ph_iso(last.ot_break_out_at),
                ot_break_in_at=to_ph_iso(last.ot_break_in_at),
                expected_clock_in_at=to_ph_iso(last.expected_clock_in_at),
                expected_clock_out_at=to_ph_iso(last.expected_clock_out_at),
                break_rules=break_rules,
            )


async def resolve_schedule_day(
    session: AsyncSession,
    employee_id: UUID,
    work_date: date,
) -> ScheduleDayConfiguration:
    emergency_request = await session.scalar(
        select(EmergencyScheduleRequestModel).where(
            EmergencyScheduleRequestModel.employee_id == employee_id,
            EmergencyScheduleRequestModel.work_date == work_date,
            EmergencyScheduleRequestModel.status == "APPROVED",
        )
    )
    assignment_row = (
        await session.execute(
            select(
                EmployeeScheduleAssignmentModel,
                RestDayPatternModel.cycle_length_days,
            )
            .outerjoin(
                RestDayPatternModel,
                RestDayPatternModel.id == EmployeeScheduleAssignmentModel.rest_day_pattern_id,
            )
            .where(
                EmployeeScheduleAssignmentModel.employee_id == employee_id,
                EmployeeScheduleAssignmentModel.is_active.is_(True),
                EmployeeScheduleAssignmentModel.status == "APPROVED",
                EmployeeScheduleAssignmentModel.effective_from <= work_date,
                or_(
                    EmployeeScheduleAssignmentModel.effective_to.is_(None),
                    EmployeeScheduleAssignmentModel.effective_to >= work_date,
                ),
            )
            .order_by(
                EmployeeScheduleAssignmentModel.effective_from.desc(),
                EmployeeScheduleAssignmentModel.created_at.desc(),
            )
            .limit(1)
        )
    ).first()

    if assignment_row is None and emergency_request is None:
        return ScheduleDayConfiguration(
            work_type="REG",
            expected_clock_in_at=datetime.combine(
                work_date,
                DEFAULT_EXPECTED_CLOCK_IN,
                tzinfo=PH_TIMEZONE,
            ),
            expected_clock_out_at=datetime.combine(
                work_date,
                DEFAULT_EXPECTED_CLOCK_OUT,
                tzinfo=PH_TIMEZONE,
            ),
        )

    assignment = None
    pattern_day = None
    cycle_day_no = None
    if assignment_row is not None:
        assignment, cycle_length_days = assignment_row
        if assignment.rest_day_pattern_id is not None:
            if cycle_length_days is None:
                raise RuntimeError("The assigned rest-day pattern could not be loaded.")
            cycle_day_no = get_cycle_day_number(
                assignment.effective_from,
                work_date,
                cycle_length_days,
            )
            pattern_day = await session.scalar(
                select(RestDayPatternDayModel).where(
                    RestDayPatternDayModel.pattern_id == assignment.rest_day_pattern_id,
                    RestDayPatternDayModel.cycle_day_no == cycle_day_no,
                )
            )
            if pattern_day is None:
                raise RuntimeError(
                    "The assigned rest-day pattern is missing a cycle day "
                    f"({cycle_day_no})."
                )

    is_workday = pattern_day is None or pattern_day.is_workday
    schedule_template_id = None
    schedule_context: dict[str, Any] = {}
    if assignment is not None:
        schedule_template_id = (
            pattern_day.schedule_template_id or assignment.schedule_template_id
            if pattern_day is not None
            else assignment.schedule_template_id
        )
        schedule_context["schedule_assignment_id"] = str(assignment.id)
    if emergency_request is not None:
        schedule_template_id = emergency_request.schedule_template_id
        is_workday = True
        schedule_context["emergency_schedule_request_id"] = str(emergency_request.id)
    if schedule_template_id is not None:
        schedule_context["schedule_template_id"] = str(schedule_template_id)
    if assignment is not None and assignment.rest_day_pattern_id is not None and cycle_day_no is not None:
        schedule_context["rest_day_pattern_id"] = str(assignment.rest_day_pattern_id)
        schedule_context["cycle_day_no"] = cycle_day_no
    if not is_workday:
        return ScheduleDayConfiguration(
            work_type="REST",
            expected_clock_in_at=None,
            expected_clock_out_at=None,
            schedule_context=schedule_context,
        )

    template = await session.get(ScheduleTemplateModel, schedule_template_id)
    if template is None:
        raise RuntimeError("The employee's assigned schedule template could not be loaded.")
    schedule_context.update(
        {
            "grace_minutes": template.grace_minutes,
            "ot_eligible": template.ot_eligible,
            "minimum_ot_minutes": template.minimum_ot_minutes,
            "pre_shift_ot_allowed": template.pre_shift_ot_allowed,
        }
    )
    work_segments = list(
        (
            await session.scalars(
                select(ScheduleSegmentModel)
                .where(
                    ScheduleSegmentModel.schedule_template_id == schedule_template_id,
                    ScheduleSegmentModel.segment_type == "WORK",
                )
                .order_by(ScheduleSegmentModel.segment_sequence)
            )
        ).all()
    )
    if not work_segments:
        raise RuntimeError(
            f"Schedule template {template.schedule_code} has no WORK segments."
        )

    first_segment = work_segments[0]
    last_segment = work_segments[-1]
    schedule_context["early_clock_in_allowance_minutes"] = first_segment.flex_start_minutes
    break_segments = list((await session.scalars(
        select(ScheduleSegmentModel).where(
            ScheduleSegmentModel.schedule_template_id == schedule_template_id,
            ScheduleSegmentModel.break_slot.is_not(None),
        )
    )).all())
    schedule_context["break_rules"] = [
        {
            "segment_id": str(segment.id),
            "break_slot": segment.break_slot,
            "segment_type": segment.segment_type,
            "break_minutes": segment.break_minutes,
            "auto_deduct": segment.auto_deduct,
            "start_at": datetime.combine(work_date, segment.start_time, tzinfo=PH_TIMEZONE).isoformat(),
            "end_at": datetime.combine(
                work_date + timedelta(days=segment.end_day_offset),
                segment.end_time, tzinfo=PH_TIMEZONE,
            ).isoformat(),
        }
        for segment in break_segments
    ]
    expected_start = datetime.combine(
        work_date,
        first_segment.start_time,
        tzinfo=PH_TIMEZONE,
    )
    expected_end = datetime.combine(
        work_date + timedelta(days=last_segment.end_day_offset),
        last_segment.end_time,
        tzinfo=PH_TIMEZONE,
    )
    if expected_end <= expected_start:
        raise RuntimeError(
            f"Schedule template {template.schedule_code} has an end time that is not after its start time."
        )
    return ScheduleDayConfiguration(
        work_type="REG",
        expected_clock_in_at=expected_start,
        expected_clock_out_at=expected_end,
        schedule_template_id=schedule_template_id,
        grace_minutes=template.grace_minutes,
        ot_eligible=template.ot_eligible,
        minimum_ot_minutes=template.minimum_ot_minutes,
        pre_shift_ot_allowed=template.pre_shift_ot_allowed,
        schedule_context=schedule_context,
        early_clock_in_allowance_minutes=first_segment.flex_start_minutes,
    )


class ClockAttendanceUseCase(BaseUseCase[ClockAttendanceOutputDTO]):
    """
    Attendance entry point. The captured face is matched to the selected employee's enrollment.
    """

    def __init__(self, uow: GenUnitOfWork, face_recognition_service):
        self.uow = uow
        self.face_recognition_service = face_recognition_service

    def _get_last_punch_time(self, existing: AttendanceEntity) -> datetime:
        """Find the most recent punch across all fields to apply the 5-minute validation safely."""
        return get_last_punch_time(existing) or datetime.min.replace(tzinfo=timezone.utc)

    async def _validate_clock_in_geofence(
        self,
        uow: GenUnitOfWork,
        user: UserEntity,
        latitude: float | None,
        longitude: float | None,
        accuracy_meters: float | None,
        now_utc: datetime,
        today: date,
        allow_wfh: bool = False,
    ) -> dict[str, Any]:
        logger.info(
            "Attendance GPS received: latitude=%s longitude=%s accuracy_meters=%s",
            latitude,
            longitude,
            accuracy_meters,
        )
        if latitude is None or longitude is None or accuracy_meters is None:
            logger.warning("Attendance GPS validation failed: one or more GPS values were not provided.")
            raise ValueError("Allow location access to clock in or out.")
        if (
            not all(isfinite(value) for value in (latitude, longitude, accuracy_meters))
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
            or accuracy_meters <= 0
        ):
            logger.warning(
                "Attendance GPS validation failed: invalid values latitude=%s longitude=%s accuracy_meters=%s",
                latitude,
                longitude,
                accuracy_meters,
            )
            raise ValueError("The device returned invalid GPS coordinates or accuracy.")
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")

        employee = await uow.session.scalar(
            select(EmployeeModel).where(
                EmployeeModel.id == user.employee_id,
                EmployeeModel.is_active.is_(True),
                EmployeeModel.record_status == "ACTIVE",
            )
        )
        if employee is None:
            raise ValueError("No active employee record is linked to this account.")

        # Each active assignment grants only the geofences explicitly linked to it.
        assignments = list(
            (
                await uow.session.scalars(
                    select(EmploymentAssignmentModel).where(
                        EmploymentAssignmentModel.employee_id == employee.id,
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
            ).all()
        )
        if not assignments:
            raise ValueError("No active authorized geofence location is assigned to this employee.")

        locations = list(
            (
                await uow.session.scalars(
                    select(LocationModel)
                    .join(Geofence, Geofence.location_id == LocationModel.id)
                    .join(
                        EmploymentAssignmentGeofenceModel,
                        and_(
                            EmploymentAssignmentGeofenceModel.geofence_id == Geofence.id,
                            EmploymentAssignmentGeofenceModel.company_id == Geofence.company_id,
                        ),
                    )
                    .join(
                        EmploymentAssignmentModel,
                        and_(
                            EmploymentAssignmentModel.id == EmploymentAssignmentGeofenceModel.assignment_id,
                            EmploymentAssignmentModel.company_id == EmploymentAssignmentGeofenceModel.company_id,
                        ),
                    )
                    .where(
                        EmploymentAssignmentModel.id.in_([item.id for item in assignments]),
                        LocationModel.company_id == Geofence.company_id,
                        LocationModel.is_active.is_(True),
                        LocationModel.status == "ACTIVE",
                    )
                    .distinct()
                )
            ).all()
        )
        if not locations:
            raise ValueError("The employee's assigned locations are inactive or unavailable.")
        locations_by_id = {location.id: location for location in locations}

        geofences = list(
            (
                await uow.session.scalars(
                    select(Geofence)
                    .join(
                        EmploymentAssignmentGeofenceModel,
                        EmploymentAssignmentGeofenceModel.geofence_id == Geofence.id,
                    )
                    .join(
                        EmploymentAssignmentModel,
                        and_(
                            EmploymentAssignmentModel.id == EmploymentAssignmentGeofenceModel.assignment_id,
                            EmploymentAssignmentModel.company_id == EmploymentAssignmentGeofenceModel.company_id,
                        ),
                    )
                    .join(
                        LocationModel,
                        and_(
                            LocationModel.id == Geofence.location_id,
                            LocationModel.company_id == Geofence.company_id,
                        ),
                    )
                    .where(
                        EmploymentAssignmentModel.employee_id == employee.id,
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
                        LocationModel.is_active.is_(True),
                        LocationModel.status == "ACTIVE",
                        Geofence.is_active.is_(True),
                        Geofence.status == "ACTIVE",
                        Geofence.effective_from <= now_utc,
                        or_(Geofence.effective_to.is_(None), Geofence.effective_to >= now_utc),
                    )
                )
            ).all()
        )
        if not geofences:
            raise ValueError("No active assigned geofence is configured for this employee.")

        wfh = await uow.session.get(EmployeeWfhLocationModel, employee.id) if allow_wfh else None
        wfh_fence = next(
            (
                fence for fence in geofences
                if wfh is not None and wfh.is_active and fence.id == wfh.geofence_id
                and fence.radius_meters is not None and fence.radius_meters > 0
            ),
            None,
        )
        eligible_geofences = [
            geofence for geofence in geofences
            if accuracy_meters <= geofence.maximum_gps_accuracy_meters
        ]
        logger.info(
            "Attendance GPS accuracy check: reported_accuracy_meters=%.2f geofence_limits_meters=%s eligible_geofence_ids=%s",
            accuracy_meters,
            [
                {
                    "geofence_id": str(geofence.id),
                    "maximum_gps_accuracy_meters": geofence.maximum_gps_accuracy_meters,
                    "accepted": accuracy_meters <= geofence.maximum_gps_accuracy_meters,
                }
                for geofence in geofences
            ],
            [str(geofence.id) for geofence in eligible_geofences],
        )
        if not eligible_geofences:
            maximum_accuracy = max(item.maximum_gps_accuracy_meters for item in geofences)
            raise ValueError(
                f"GPS accuracy is too low. Move outdoors and try again (required accuracy: {maximum_accuracy} m or better)."
            )

        point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
        point_geography = cast(point, Geography(srid=4326))
        point_geometry = cast(point, Geometry(srid=4326))
        wfh_condition = None
        if wfh is not None and wfh_fence is not None and wfh_fence in eligible_geofences:
            home_point = cast(
                func.ST_SetSRID(func.ST_MakePoint(wfh.longitude, wfh.latitude), 4326),
                Geography(srid=4326),
            )
            wfh_condition = and_(
                Geofence.id == wfh_fence.id,
                circle_contains_gps(home_point, point_geography, Geofence.radius_meters, accuracy_meters),
            )
        fence_conditions = []
        for geofence in eligible_geofences:
            if geofence.center_point is not None and geofence.radius_meters is not None:
                fence_conditions.append(
                    and_(
                        Geofence.id == geofence.id,
                        circle_contains_gps(
                            Geofence.center_point,
                            point_geography,
                            Geofence.radius_meters,
                            accuracy_meters,
                        ),
                    )
                )
            if geofence.boundary_polygon is not None:
                polygon = cast(Geofence.boundary_polygon, Geometry(srid=4326))
                fence_conditions.append(
                    and_(
                        Geofence.id == geofence.id,
                        func.ST_Covers(polygon, point_geometry),
                        func.ST_Distance(
                            cast(func.ST_Boundary(polygon), Geography(srid=4326)),
                            point_geography,
                        ) >= accuracy_meters,
                    )
                )

        if wfh_condition is not None:
            fence_conditions.append(wfh_condition)
        if not fence_conditions:
            raise ValueError("The assigned geofence has no supported boundary.")
        matched = (
            await uow.session.execute(
                select(
                    Geofence.id, Geofence.company_id, Geofence.location_id,
                    case((wfh_condition, True), else_=False).label("is_wfh")
                    if wfh_condition is not None else false().label("is_wfh"),
                )
                .where(or_(*fence_conditions))
                .order_by(func.ST_Distance(Geofence.center_point, point_geography).nulls_last())
                .limit(1)
            )
        ).first()
        if matched is None:
            distance_rows = (
                await uow.session.execute(
                    select(
                        Geofence.id,
                        Geofence.radius_meters,
                        func.ST_Distance(Geofence.center_point, point_geography).label("center_distance"),
                        func.ST_Distance(Geofence.boundary_polygon, point_geography).label("polygon_distance"),
                    ).where(Geofence.id.in_([geofence.id for geofence in eligible_geofences]))
                )
            ).all()
            diagnostics = [
                {
                    "geofence_id": str(row.id),
                    "center_distance_meters": round(float(row.center_distance), 2) if row.center_distance is not None else None,
                    "radius_meters": float(row.radius_meters) if row.radius_meters is not None else None,
                    "polygon_distance_meters": round(float(row.polygon_distance), 2) if row.polygon_distance is not None else None,
                }
                for row in distance_rows
            ]
            if wfh is not None and wfh_condition is not None and wfh_fence is not None:
                home_distance = await uow.session.scalar(select(func.ST_Distance(home_point, point_geography)))
                diagnostics.append({
                    "geofence_id": str(wfh_fence.id),
                    "work_location_type": "WFH",
                    "center_distance_meters": round(float(home_distance), 2),
                    "radius_meters": float(wfh_fence.radius_meters),
                    "polygon_distance_meters": None,
                })
            logger.warning(
                "Attendance geofence rejected: latitude=%s longitude=%s accuracy_meters=%.2f diagnostics=%s",
                latitude,
                longitude,
                accuracy_meters,
                diagnostics,
            )
            # Distance the reported point must move inward (including GPS uncertainty) to be accepted.
            shortfalls = [
                item["center_distance_meters"] + accuracy_meters - item["radius_meters"]
                for item in diagnostics
                if item["center_distance_meters"] is not None and item["radius_meters"] is not None
            ]
            if shortfalls:
                raise ValueError(
                    "You are outside the allowed attendance area of your assigned locations"
                    + (" or registered WFH location " if wfh_condition is not None else " ")
                    + f"(about {max(1, round(min(shortfalls)))} m outside the nearest one, including GPS accuracy of "
                    f"{round(accuracy_meters)} m)."
                )
            raise ValueError(
                "You are outside the allowed attendance area of your assigned locations"
                + (" or registered WFH location." if wfh_condition is not None else ".")
            )

        matched_location = locations_by_id.get(matched.location_id)
        metadata = {
            "latitude": latitude,
            "longitude": longitude,
            "accuracy_meters": accuracy_meters,
            "company_id": str(matched.company_id),
            "location_id": str(matched.location_id),
            "location_name": getattr(matched_location, "location_name", None),
            "geofence_id": str(matched.id),
            "authorized_location_ids": [str(location_id) for location_id in locations_by_id],
        }
        if matched.is_wfh and wfh is not None and wfh_fence is not None:
            metadata.update({
                "work_location_type": "WFH",
                "registered_latitude": wfh.latitude,
                "registered_longitude": wfh.longitude,
                "radius_meters": float(wfh_fence.radius_meters),
                "maximum_gps_accuracy_meters": wfh_fence.maximum_gps_accuracy_meters,
                "wfh_registration_version": wfh.row_version,
            })
        return metadata

    async def _resolve_day_type(
        self,
        uow: GenUnitOfWork,
        employee_id: UUID,
        work_date: date,
    ) -> str:
        """Day type from the published holiday calendar; REG when no holiday applies.

        Local holiday eligibility follows the assignment's primary work location,
        not whichever authorized site accepted the punch.
        """
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")

        row = (
            await uow.session.execute(
                select(
                    EmploymentAssignmentModel.company_id,
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
                    EmploymentAssignmentModel.employee_id == employee_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.effective_from <= work_date,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= work_date,
                    ),
                )
                .order_by(EmploymentAssignmentModel.effective_from.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return "REG"
        (
            company_id,
            region,
            province,
            city,
            psgc_region_code,
            psgc_province_code,
            psgc_city_code,
            ncr_district,
        ) = row

        location_scope = GeographicArea(
            region=region,
            province=province,
            city=city,
            psgc_region_code=psgc_region_code,
            psgc_province_code=psgc_province_code,
            psgc_city_code=psgc_city_code,
            ncr_district=ncr_district,
        )

        holidays = (
            await uow.session.execute(
                select(HolidayModel, HolidayCalendarModel)
                .join(HolidayCalendarModel, HolidayCalendarModel.id == HolidayModel.holiday_calendar_id)
                .where(
                    HolidayCalendarModel.company_id == company_id,
                    HolidayCalendarModel.effective_year == work_date.year,
                    HolidayCalendarModel.status == "PUBLISHED",
                    HolidayCalendarModel.is_active.is_(True),
                    HolidayModel.holiday_date == work_date,
                    HolidayModel.status == "ACTIVE",
                    HolidayModel.is_active.is_(True),
                )
            )
        ).all()

        best: str | None = None
        best_rank = len(HOLIDAY_DAY_TYPE_PRIORITY)
        for holiday, calendar in holidays:
            if not holiday_applies_to_location(
                holiday.holiday_type,
                holiday,
                location_scope,
            ):
                continue
            code = "DBL" if holiday.is_double_holiday else HOLIDAY_DAY_TYPES.get(holiday.holiday_type)
            if code is None:
                continue
            rank = HOLIDAY_DAY_TYPE_PRIORITY.index(code)
            if rank < best_rank:
                best, best_rank = code, rank
        return best or "REG"

    async def _resolve_schedule_day(
        self,
        uow: GenUnitOfWork,
        employee_id: UUID,
        work_date: date,
    ) -> ScheduleDayConfiguration:
        if uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        return await resolve_schedule_day(uow.session, employee_id, work_date)

    async def _execute(self, input_dto: ClockAttendanceInputDTO) -> ClockAttendanceOutputDTO:
        candidate_encoding = self.face_recognition_service.extract_face_encoding(input_dto.image_bytes)
        async with self.uow as uow:
            user_repo = uow.get_repo(UserEntity, UserModel)
            user = await user_repo.get(input_dto.user_id)
            if not user or not user.is_active or user.account_status != AccountStatus.ACTIVE.value:
                raise ValueError("Matched account is inactive or no longer exists.")

            employee_repo = uow.get_repo(EmployeeEntity, EmployeeModel)
            employee = (
                await employee_repo.find_one(EmployeeModel.id == user.employee_id)
                if user.employee_id
                else None
            )
            if not employee or not employee.is_active or employee.record_status != "ACTIVE":
                raise ValueError("No active employee profile is linked to this account.")

            enrollment_repo = uow.get_repo(FaceEnrollmentEntity, FaceEnrollmentModel)
            # Load every employee's enrolled samples so a face closer to someone else is rejected (1:N check).
            enrollments = await enrollment_repo.find_all(
                FaceEnrollmentModel.status == EnrollmentStatus.ENROLLED,
                limit=MAX_FACE_MATCH_CANDIDATES,
            )
            known_encodings = [(e.employee_id, e.face_encoding) for e in enrollments if e.face_encoding]
            if not any(employee_id == employee.id for employee_id, _ in known_encodings):
                raise ValueError("This employee has no active face enrollment.")

            match = self.face_recognition_service.find_best_match(candidate_encoding, known_encodings)
            if not match:
                raise ValueError("Face not recognized. Please enroll first or try again.")

            matched_employee_id, _distance = match
            if matched_employee_id != employee.id:
                raise ValueError("Face does not match the selected employee.")

            # 2. Timezone logic
            now_utc = datetime.now(timezone.utc)
            ph_timezone = ZoneInfo("Asia/Manila")
            now_local = now_utc.astimezone(ph_timezone)
            today = now_local.date()

            # 3. Find the employee's CURRENTLY ACTIVE (open) attendance record.
            # This bypasses midnight-crossover issues for night shifts.
            attendance_repo = uow.get_repo(AttendanceEntity, AttendanceModel)
            records = await attendance_repo.find_all(
                AttendanceModel.user_id == input_dto.user_id,
                func.coalesce(
                    AttendanceModel.corrected_clock_in_at,
                    AttendanceModel.clock_in_at,
                ).is_not(None),
                AttendanceModel.corrected_clock_out_at.is_(None),
                AttendanceModel.clock_out_at.is_(None),
                order_by=func.coalesce(
                    AttendanceModel.corrected_clock_in_at,
                    AttendanceModel.clock_in_at,
                ).desc(),
                limit=1,
            )
 
            existing = records[0] if records else None
            if existing is not None:
                existing_clock_in = existing.corrected_clock_in_at or existing.clock_in_at
                if (
                    existing_clock_in is not None
                    and now_utc - to_utc(existing_clock_in) >= MAX_OPEN_ATTENDANCE_AGE
                ):
                    # Keep the unclosed record for no-logout reporting, but don't
                    # let it block a new attendance record after 24 hours.
                    existing = None
            approval_required = False
            schedule_template_id: UUID | None = None
            # 3. Simplify to Clock In vs Clock Out logic
            if not existing:
                # CLOCK IN
                schedule = await self._resolve_schedule_day(
                    uow,
                    employee.id,
                    today,
                )
                if (
                    schedule.expected_clock_out_at is None
                    or now_utc >= to_utc(schedule.expected_clock_out_at)
                ):
                    next_date = today + timedelta(days=1)
                    next_schedule = await self._resolve_schedule_day(uow, employee.id, next_date)
                    if (
                        next_schedule.schedule_template_id is not None
                        and next_schedule.expected_clock_in_at is not None
                        and to_utc(next_schedule.expected_clock_in_at)
                        - timedelta(minutes=next_schedule.early_clock_in_allowance_minutes)
                        <= now_utc < to_utc(next_schedule.expected_clock_in_at)
                    ):
                        today, schedule = next_date, next_schedule
                if schedule.schedule_template_id is not None and schedule.expected_clock_in_at is not None:
                    validate_early_clock_in(
                        now_utc, schedule.expected_clock_in_at,
                        schedule.early_clock_in_allowance_minutes,
                    )
                late_minutes, _, _ = calculate_attendance_metrics(
                    expected_clock_in_at=schedule.expected_clock_in_at,
                    expected_clock_out_at=schedule.expected_clock_out_at,
                    actual_clock_in_at=now_utc,
                    actual_clock_out_at=None,
                    grace_minutes=schedule.grace_minutes,
                )
                initial_metadata = {}
                if schedule.schedule_context:
                    initial_metadata["schedule_context"] = schedule.schedule_context
                if input_dto.enforce_geofence:
                    geofence_metadata = await self._validate_clock_in_geofence(
                        uow,
                        user,
                        input_dto.latitude,
                        input_dto.longitude,
                        input_dto.gps_accuracy_meters,
                        now_utc,
                        today,
                        allow_wfh=input_dto.allow_wfh,
                    )
                    initial_metadata["clock_in"] = {"geofence_validation": geofence_metadata}
                else:
                    logger.info(
                        "Attendance geofence check skipped by clock policy=%s; GPS received latitude=%s longitude=%s accuracy_meters=%s",
                        input_dto.clock_channel,
                        input_dto.latitude,
                        input_dto.longitude,
                        input_dto.gps_accuracy_meters,
                    )
                    initial_metadata["clock_in"] = {
                        "geofence_validation": "disabled",
                        "location_report": {
                            "latitude": input_dto.latitude,
                            "longitude": input_dto.longitude,
                            "accuracy_meters": input_dto.gps_accuracy_meters,
                        } if input_dto.latitude is not None else None,
                    }
                if input_dto.clock_channel:
                    initial_metadata["clock_in"]["clock_policy"] = input_dto.clock_channel
                if input_dto.punch_metadata:
                    initial_metadata["clock_in"].update(input_dto.punch_metadata)
                if not input_dto.device_approved:
                    initial_metadata["clock_in"]["approval_required"] = "Browser approval is required."

                created = await attendance_repo.add(
                    AttendanceEntity(
                        user_id=input_dto.user_id,
                        work_date=today,
                        expected_clock_in_at=schedule.expected_clock_in_at,
                        expected_clock_out_at=schedule.expected_clock_out_at,
                        schedule_template_id=schedule.schedule_template_id,
                        clock_in_at=now_utc,
                        day_type=await self._resolve_day_type(uow, employee.id, today),
                        work_type=schedule.work_type,
                        late_minutes=late_minutes,
                        record_status="VALID" if input_dto.device_approved else "INVALID",
                        punch_metadata=initial_metadata
                    )
                )
                action_taken = "clock_in"
                timestamp = created.clock_in_at
                approval_required = created.record_status == "INVALID"
                schedule_template_id = created.schedule_template_id
                late_minutes = created.late_minutes
                undertime_minutes = created.undertime_minutes
                calculated_ot_minutes = created.calculated_ot_minutes
                overtime_hours = float(created.overtime_hours)
                regular_overtime_minutes = created.regular_overtime_minutes
                regular_overtime_hours = float(created.regular_overtime_hours)
                night_differential_overtime_minutes = created.night_differential_overtime_minutes
                night_differential_overtime_hours = float(created.night_differential_overtime_hours)
                night_differential_hours = float(created.night_differential_hours)
                
            else:
                # CLOCK OUT
                if existing.is_locked:
                    raise ValueError("This attendance record has been locked by HR for payroll. No further punches allowed.")
                
                if existing.clock_out_at:
                    raise ValueError("Attendance for today is already complete (clocked in and out).")

                if not input_dto.clock_out_confirmed and existing.expected_clock_out_at:
                    expected_clock_out = to_utc(existing.expected_clock_out_at)
                    if now_utc < expected_clock_out:
                        remaining_minutes = max(
                            1,
                            int((expected_clock_out - now_utc).total_seconds() / 60) + 1,
                        )
                        raise ValueError(
                            f"Shift hours are not yet completed. Please wait {remaining_minutes} more minute(s)."
                        )

                # 5-Minute Validation Check against whatever their most recent action was
                last_punch = self._get_last_punch_time(existing)
                time_elapsed = now_utc - last_punch
                if time_elapsed < timedelta(minutes=5):
                    raise ValueError(f"Action rejected. Please wait at least 5 minutes. Time elapsed: {int(time_elapsed.total_seconds() / 60)} minutes.")

                # Warn/Block if they try to clock out while a break is still active
                active_break = get_active_break(existing)
                if active_break:
                    raise ValueError(f"You must end your active {active_break} before clocking out.")

                existing.clock_out_at = now_utc
                clock_out_geofence: Any = None
                if input_dto.enforce_geofence:
                    clock_out_geofence = await self._validate_clock_in_geofence(
                        uow,
                        user,
                        input_dto.latitude,
                        input_dto.longitude,
                        input_dto.gps_accuracy_meters,
                        now_utc,
                        existing.work_date,
                        allow_wfh=input_dto.allow_wfh,
                    )
                schedule_context = (existing.punch_metadata or {}).get("schedule_context", {})
                expected_clock_in = existing.expected_clock_in_at
                expected_clock_out = existing.expected_clock_out_at
                schedule_policy = None
                if "ot_eligible" not in schedule_context and schedule_context.get("schedule_template_id"):
                    schedule_policy = await uow.session.get(
                        ScheduleTemplateModel,
                        UUID(str(schedule_context["schedule_template_id"])),
                    )
                actual_clock_in = existing.corrected_clock_in_at or existing.clock_in_at
                break_rules = await resolve_record_break_rules(uow, existing)
                break_excess_minutes, unpaid_break_minutes, break_intervals = calculate_break_policy(
                    existing, break_rules,
                )
                regular_overtime_minutes, night_differential_overtime_minutes, calculated_ot_minutes = (
                    calculate_overtime_breakdown(
                        expected_clock_in_at=expected_clock_in,
                        expected_clock_out_at=expected_clock_out,
                        actual_clock_in_at=actual_clock_in,
                        actual_clock_out_at=now_utc,
                        ot_eligible=bool(
                            schedule_context.get(
                                "ot_eligible",
                                schedule_policy.ot_eligible if schedule_policy else False,
                            )
                        ),
                        minimum_ot_minutes=int(
                            schedule_context.get(
                                "minimum_ot_minutes",
                                schedule_policy.minimum_ot_minutes if schedule_policy else 0,
                            )
                        ),
                        pre_shift_ot_allowed=bool(
                            schedule_context.get(
                                "pre_shift_ot_allowed",
                                schedule_policy.pre_shift_ot_allowed if schedule_policy else False,
                            )
                        ),
                        break_intervals=break_intervals,
                    )
                )
                late_minutes, undertime_minutes, _ = calculate_attendance_metrics(
                    expected_clock_in_at=expected_clock_in,
                    expected_clock_out_at=expected_clock_out,
                    actual_clock_in_at=actual_clock_in,
                    actual_clock_out_at=now_utc,
                    grace_minutes=int(
                        schedule_context.get(
                            "grace_minutes",
                            schedule_policy.grace_minutes if schedule_policy else 0,
                        )
                    ),
                    ot_eligible=bool(
                        schedule_context.get(
                            "ot_eligible",
                            schedule_policy.ot_eligible if schedule_policy else False,
                        )
                    ),
                    minimum_ot_minutes=int(
                        schedule_context.get(
                            "minimum_ot_minutes",
                            schedule_policy.minimum_ot_minutes if schedule_policy else 0,
                        )
                    ),
                    pre_shift_ot_allowed=bool(
                        schedule_context.get(
                            "pre_shift_ot_allowed",
                            schedule_policy.pre_shift_ot_allowed if schedule_policy else False,
                        )
                    ),
                    break_intervals=break_intervals,
                )
                night_differential_minutes = calculate_night_differential_minutes(
                    actual_clock_in_at=actual_clock_in,
                    actual_clock_out_at=now_utc,
                    break_intervals=break_intervals,
                )
                existing.late_minutes = late_minutes
                existing.undertime_minutes = undertime_minutes
                existing.calculated_ot_minutes = calculated_ot_minutes
                existing.overtime_hours = Decimal(calculated_ot_minutes) / Decimal(60)
                existing.regular_overtime_minutes = regular_overtime_minutes
                existing.regular_overtime_hours = Decimal(regular_overtime_minutes) / Decimal(60)
                existing.night_differential_overtime_minutes = night_differential_overtime_minutes
                existing.night_differential_overtime_hours = (
                    Decimal(night_differential_overtime_minutes) / Decimal(60)
                )
                existing.night_differential_minutes = night_differential_minutes
                existing.night_differential_hours = Decimal(night_differential_minutes) / Decimal(60)
                existing.approved_night_differential_minutes = night_differential_minutes
                existing.approved_night_diff = night_differential_minutes / 60

                # Merge the new metadata cleanly
                current_meta = existing.punch_metadata or {}
                net_nonpayable_minutes = calculate_net_nonpayable_break_minutes(
                    existing,
                    break_rules,
                    break_intervals,
                    actual_clock_in,
                    now_utc,
                )
                current_meta["break_calculation"] = {
                    "excess_undertime_minutes": break_excess_minutes,
                    "excess_minutes_break": break_excess_minutes,
                    "unpaid_break_minutes": unpaid_break_minutes,
                    "net_nonpayable_minutes": net_nonpayable_minutes,
                    "undertime_excludes_break_excess": True,
                }
                clock_out_meta = dict(input_dto.punch_metadata or {})
                if clock_out_geofence is not None:
                    clock_out_meta["geofence_validation"] = clock_out_geofence
                if input_dto.clock_channel:
                    clock_out_meta["clock_policy"] = input_dto.clock_channel
                if not input_dto.device_approved:
                    existing.record_status = "INVALID"
                    clock_out_meta["approval_required"] = "Browser approval is required."
                if clock_out_meta:
                    current_meta["clock_out"] = clock_out_meta
                existing.punch_metadata = current_meta

                updated = await attendance_repo.update(existing)
                action_taken = "clock_out"
                timestamp = updated.clock_out_at
                approval_required = updated.record_status == "INVALID"
                schedule_template_id = updated.schedule_template_id
                overtime_hours = float(updated.overtime_hours)
                regular_overtime_minutes = updated.regular_overtime_minutes
                regular_overtime_hours = float(updated.regular_overtime_hours)
                night_differential_overtime_minutes = updated.night_differential_overtime_minutes
                night_differential_overtime_hours = float(updated.night_differential_overtime_hours)
                night_differential_hours = float(updated.night_differential_hours)

            return ClockAttendanceOutputDTO(
                employee_name=employee_display_name(employee),
                employee_code=employee.employee_no,
                action=action_taken,
                timestamp=timestamp.astimezone(ph_timezone).isoformat(),
                schedule_template_id=schedule_template_id,
                approval_required=approval_required,
                late_minutes=late_minutes,
                undertime_minutes=undertime_minutes,
                calculated_ot_minutes=calculated_ot_minutes,
                overtime_hours=overtime_hours,
                regular_overtime_minutes=regular_overtime_minutes,
                regular_overtime_hours=regular_overtime_hours,
                night_differential_overtime_minutes=night_differential_overtime_minutes,
                night_differential_overtime_hours=night_differential_overtime_hours,
                night_differential_hours=night_differential_hours,
            )


@dataclass(frozen=True)
class RecordBreakInputDTO:
    user_id: UUID
    break_type: str  # e.g., "first_break_out_at", "meal_break_in_at", etc.
    image_bytes: bytes
    device_proof: Optional[Dict[str, str]] = None
    punch_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class RecordBreakOutputDTO:
    employee_name: str
    employee_code: str
    action_recorded: str  # e.g., "first_break_out_at", "meal_break_in_at", etc.
    timestamp: str


class RecordBreakUseCase(BaseUseCase[RecordBreakOutputDTO]):
    """Records a break after matching the employee's face enrollment."""

    def __init__(self, uow: GenUnitOfWork, face_recognition_service):
        self.uow = uow
        self.face_recognition_service = face_recognition_service

    async def _execute(self, input_dto: RecordBreakInputDTO) -> RecordBreakOutputDTO:
        candidate_encoding = self.face_recognition_service.extract_face_encoding(input_dto.image_bytes)
        async with self.uow as uow:
            user_repo = uow.get_repo(UserEntity, UserModel)
            user = await user_repo.get(input_dto.user_id)
            if not user or not user.is_active or user.account_status != AccountStatus.ACTIVE.value:
                raise ValueError("Employee account is inactive or does not exist.")

            employee_repo = uow.get_repo(EmployeeEntity, EmployeeModel)
            employee = (
                await employee_repo.find_one(EmployeeModel.id == user.employee_id)
                if user.employee_id
                else None
            )
            if not employee or not employee.is_active or employee.record_status != "ACTIVE":
                raise ValueError("No active employee profile is linked to this account.")

            enrollment_repo = uow.get_repo(FaceEnrollmentEntity, FaceEnrollmentModel)
            enrollments = await enrollment_repo.find_all(
                FaceEnrollmentModel.status == EnrollmentStatus.ENROLLED,
                limit=MAX_FACE_MATCH_CANDIDATES,
            )
            known_encodings = [(item.employee_id, item.face_encoding) for item in enrollments if item.face_encoding]
            if not any(employee_id == employee.id for employee_id, _ in known_encodings):
                raise ValueError("This employee has no active face enrollment.")
            match = self.face_recognition_service.find_best_match(candidate_encoding, known_encodings)
            if not match or match[0] != employee.id:
                raise ValueError("Face not recognized for this employee. Please enroll or try again.")

            # 2. Get current local date in Philippine Time
            now_utc = datetime.now(timezone.utc)
            ph_timezone = ZoneInfo("Asia/Manila")
            now_local = now_utc.astimezone(ph_timezone)
            today = now_local.date()

            # 3. Find the employee's CURRENTLY ACTIVE (open) attendance record.
            # This bypasses midnight-crossover issues for night shifts.
            attendance_repo = uow.get_repo(AttendanceEntity, AttendanceModel)
            records = await attendance_repo.find_all(
                AttendanceModel.user_id == input_dto.user_id,
                func.coalesce(
                    AttendanceModel.corrected_clock_in_at,
                    AttendanceModel.clock_in_at,
                ).is_not(None),
                AttendanceModel.corrected_clock_out_at.is_(None),
                AttendanceModel.clock_out_at.is_(None),
                order_by=func.coalesce(
                    AttendanceModel.corrected_clock_in_at,
                    AttendanceModel.clock_in_at,
                ).desc(),
                limit=1,
            )

            if not records:
                raise ValueError("No active shift found. Please Clock In first.")

            existing = records[0]

            # 4. Check if record is locked for payroll
            if existing.is_locked:
                raise ValueError("This attendance record has been locked by HR. No further punches allowed.")

            # 5. Validate the requested timestamp field and break sequence.
            break_pairs = {start: (end, label) for start, end, label in BREAK_PAIRS}
            break_ends = {end: (start, label) for start, end, label in BREAK_PAIRS}
            target_field = input_dto.break_type
            break_rules = await resolve_record_break_rules(uow, existing)
            rule = next((
                item for item in break_rules
                if target_field in BREAK_SLOT_FIELDS[item["break_slot"]]
            ), None)
            if target_field not in break_pairs and target_field not in break_ends:
                raise ValueError("Invalid break type.")
            if break_rules and rule is None and target_field in break_pairs and not target_field.startswith("ot_"):
                raise ValueError("This attendance break has no configured schedule segment.")
            if target_field == "ot_break_out_at" and rule is None:
                raise ValueError("Configure an OT_BREAK paid allowance in the schedule template first.")
            if getattr(existing, target_field) is not None:
                raise ValueError("This break action has already been recorded.")

            if target_field in break_ends:
                start_field, label = break_ends[target_field]
                if getattr(existing, start_field) is None:
                    raise ValueError(f"You cannot end the {label} because it has not been started.")
            else:
                active_break = get_active_break(existing)
                if active_break:
                    raise ValueError(f"You must end your active {active_break} first.")
                has_meal_rule = any(item.get("break_slot") == "MEAL_BREAK" for item in break_rules)
                has_first_rule = any(item.get("break_slot") == "FIRST_BREAK" for item in break_rules)
                if target_field == "first_break_out_at" and existing.second_break_out_at is not None:
                    raise ValueError("First break is no longer available after the second break has started.")
                if target_field == "second_break_out_at":
                    if (has_meal_rule or not break_rules) and existing.meal_break_in_at is None:
                        raise ValueError("Second break is only available after the meal break has ended.")
                    if has_first_rule and existing.first_break_in_at is None:
                        raise ValueError("Second break is only available after the first break has ended.")
                if target_field == "ot_break_out_at" and (
                    existing.expected_clock_out_at is None
                    or now_utc < to_utc(existing.expected_clock_out_at)
                ):
                    raise ValueError("Overtime break is only available after the scheduled shift end.")

            last_punch = get_last_punch_time(existing)
            if last_punch is not None and now_utc <= last_punch:
                raise ValueError("Break punch time must be later than the previous attendance punch.")

            if rule is not None and target_field in break_pairs:
                window_start = to_utc(datetime.fromisoformat(rule["start_at"]))
                window_end = to_utc(datetime.fromisoformat(rule["end_at"]))
                if (
                    target_field != "ot_break_out_at"
                    and not window_start <= now_utc < window_end
                ):
                    raise ValueError("This break must start within its linked WORK segment's time range.")

            # 6. Assign the timestamp to the target field dynamically
            setattr(existing, target_field, now_utc)
            if rule is not None and target_field in break_ends:
                excess, unpaid, _ = calculate_break_policy(existing, break_rules, require_complete=False)
                metadata = dict(existing.punch_metadata or {})
                break_calculation = dict(metadata.get("break_calculation") or {})
                previous = int(break_calculation.get("excess_undertime_minutes", 0))
                if not break_calculation.get("undertime_excludes_break_excess", False):
                    existing.undertime_minutes = max(existing.undertime_minutes - previous, 0)
                metadata["break_calculation"] = {
                    **break_calculation,
                    "excess_undertime_minutes": excess,
                    "excess_minutes_break": excess,
                    "unpaid_break_minutes": unpaid,
                    "undertime_excludes_break_excess": True,
                }
                existing.punch_metadata = metadata
            if input_dto.device_proof or input_dto.punch_metadata:
                punch_metadata = dict(existing.punch_metadata or {})
                device_proofs = dict(punch_metadata.get("device_proofs") or {})
                break_metadata = dict(device_proofs.get(target_field) or {})
                if input_dto.device_proof:
                    break_metadata["device_proof"] = input_dto.device_proof
                if input_dto.punch_metadata:
                    break_metadata.update(input_dto.punch_metadata)
                device_proofs[target_field] = break_metadata
                punch_metadata["device_proofs"] = device_proofs
                existing.punch_metadata = punch_metadata
            
            # Save update
            updated = await attendance_repo.update(existing)
            recorded_timestamp = getattr(updated, target_field)

            return RecordBreakOutputDTO(
                employee_name=employee_display_name(employee),
                employee_code=employee.employee_no,
                action_recorded=target_field,
                timestamp=recorded_timestamp.astimezone(ph_timezone).isoformat(),
            )