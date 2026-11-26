from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.application.use_case import resolve_attendance_day_type, resolve_schedule_day
from app.attendance.domain.worked_minutes import NONWORKING_DAY_TYPES
from app.filemaintenance.employees.infrastructure.db_model import EmploymentAssignmentModel
from app.filemaintenance.schedule.infrastructure.db_model import ScheduleSegmentModel

MANILA = ZoneInfo("Asia/Manila")
MAX_LEAVE_DAYS = 93
MAX_LEAVE_MINUTES_PER_DAY = 480


@dataclass(frozen=True)
class LeaveDurationDay:
    work_date: date
    requested_minutes: int


@dataclass(frozen=True)
class LeaveDuration:
    days: tuple[LeaveDurationDay, ...]
    holidays: tuple[date, ...]
    rest_days: tuple[date, ...]

    @property
    def requested_minutes(self) -> int:
        return sum(day.requested_minutes for day in self.days)


def _covered_minutes(
    start_at: datetime, end_at: datetime, work_date: date,
    segments: list[ScheduleSegmentModel], shift_start: datetime, shift_end: datetime,
) -> int:
    intervals: list[tuple[datetime, datetime]] = []
    unpaid_break = 0
    for segment in segments:
        if segment.segment_type == "UNPAID_BREAK" and segment.break_slot:
            unpaid_break += segment.break_minutes
        elif segment.segment_type == "WORK" or (
            segment.segment_type == "PAID_BREAK" and not segment.break_slot
        ):
            start = datetime.combine(work_date, segment.start_time, tzinfo=MANILA)
            end = datetime.combine(work_date + timedelta(days=segment.end_day_offset), segment.end_time, tzinfo=MANILA)
            if end <= start:
                raise ValueError(f"The schedule for {work_date} has an invalid work segment.")
            start, end = max(start, start_at), min(end, end_at)
            if start < end:
                intervals.append((start, end))
    intervals.sort()
    merged: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    minutes = sum(int((end - start).total_seconds() // 60) for start, end in merged)
    if start_at <= shift_start and end_at >= shift_end:
        minutes = max(0, minutes - unpaid_break)
    return min(minutes, MAX_LEAVE_MINUTES_PER_DAY)


async def calculate_leave_duration(
    session: AsyncSession, employee_id: UUID, start_at: datetime, end_at: datetime,
) -> LeaveDuration:
    if start_at.tzinfo is None or end_at.tzinfo is None or end_at <= start_at:
        raise ValueError("Enter a valid leave start and end time.")
    first = start_at.astimezone(MANILA).date()
    last = (end_at - timedelta(microseconds=1)).astimezone(MANILA).date()
    if first.year != last.year:
        raise ValueError("Submit separate leave applications for each entitlement year.")
    if (last - first).days + 1 > MAX_LEAVE_DAYS:
        raise ValueError(f"Leave applications are limited to {MAX_LEAVE_DAYS} calendar days.")

    days: list[LeaveDurationDay] = []
    holidays: list[date] = []
    rest_days: list[date] = []
    for offset in range(-2, (last - first).days + 1):
        work_date = first + timedelta(days=offset)
        schedule = await resolve_schedule_day(session, employee_id, work_date)
        context = schedule.schedule_context or {}
        if not (context.get("schedule_assignment_id") or context.get("emergency_schedule_request_id")):
            if work_date >= first:
                raise ValueError(f"No approved schedule is available for {work_date}. Contact HR.")
            continue
        if schedule.work_type == "REST":
            if work_date >= first:
                rest_days.append(work_date)
            continue
        if not schedule.schedule_template_id or not schedule.expected_clock_in_at or not schedule.expected_clock_out_at:
            raise ValueError(f"The approved schedule for {work_date} is incomplete. Contact HR.")
        if schedule.expected_clock_in_at >= end_at or schedule.expected_clock_out_at <= start_at:
            continue
        location_id = await session.scalar(
            select(EmploymentAssignmentModel.primary_location_id).where(
                EmploymentAssignmentModel.employee_id == employee_id,
                EmploymentAssignmentModel.is_active.is_(True),
                EmploymentAssignmentModel.status == "ACTIVE",
                EmploymentAssignmentModel.effective_from <= work_date,
                (EmploymentAssignmentModel.effective_to.is_(None) | (EmploymentAssignmentModel.effective_to >= work_date)),
            ).order_by(EmploymentAssignmentModel.effective_from.desc()).limit(1)
        )
        day_type = await resolve_attendance_day_type(session, employee_id, work_date) if location_id else "REG"
        if day_type in NONWORKING_DAY_TYPES:
            holidays.append(work_date)
            continue
        if work_date.year != first.year:
            raise ValueError("Submit separate leave applications for each entitlement year.")
        segments = list((await session.scalars(
            select(ScheduleSegmentModel).where(
                ScheduleSegmentModel.schedule_template_id == schedule.schedule_template_id,
            ).order_by(ScheduleSegmentModel.segment_sequence)
        )).all())
        minutes = _covered_minutes(
            start_at, end_at, work_date, segments,
            schedule.expected_clock_in_at, schedule.expected_clock_out_at,
        )
        if minutes:
            days.append(LeaveDurationDay(work_date, minutes))
    return LeaveDuration(tuple(days), tuple(holidays), tuple(rest_days))
