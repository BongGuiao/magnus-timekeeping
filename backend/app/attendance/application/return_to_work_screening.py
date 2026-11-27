from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.application.automatic_absence import _has_approved_exception
from app.attendance.application.use_case import resolve_attendance_day_type, resolve_schedule_day
from app.attendance.domain.return_to_work_screening import ReviewDay, ReviewDayStatus, current_absence_streak
from app.attendance.domain.worked_minutes import NONWORKING_DAY_TYPES
from app.attendance.infrastructure.attendance_merge_queries import not_merged_source
from app.attendance.infrastructure.db_model import AttendanceModel


async def review_day_status(
    session: AsyncSession,
    employee_id: UUID,
    work_date: date,
    records: list[AttendanceModel],
    now: datetime,
) -> ReviewDayStatus | None:
    """Classify a day; None means its scheduled shift is not yet complete."""
    schedule = await resolve_schedule_day(session, employee_id, work_date)
    if not schedule.schedule_context:
        return ReviewDayStatus.UNKNOWN
    day_type = await resolve_attendance_day_type(session, employee_id, work_date)
    if schedule.work_type.upper() == "REST":
        return ReviewDayStatus.REST_DAY
    if day_type.upper() in NONWORKING_DAY_TYPES:
        return ReviewDayStatus.HOLIDAY
    if schedule.schedule_template_id is None or schedule.expected_clock_out_at is None:
        return ReviewDayStatus.UNKNOWN
    if any(record.clock_in_at or record.corrected_clock_in_at for record in records):
        return ReviewDayStatus.PRESENT
    if await _has_approved_exception(session, employee_id, work_date, schedule.expected_clock_out_at):
        return ReviewDayStatus.APPROVED_LEAVE
    if now < schedule.expected_clock_out_at:
        return None
    if len(records) != 1:
        return ReviewDayStatus.UNKNOWN
    record = records[0]
    if record.is_absent and schedule.attendance_mode == "PUNCH_REQUIRED":
        return ReviewDayStatus.ABSENT
    return ReviewDayStatus.NOT_ABSENT


async def load_current_absence_streak(
    session: AsyncSession,
    user_id: UUID,
    employee_id: UUID,
    first_possible_date: date,
    today: date,
    now: datetime,
) -> tuple[date, ...]:
    records = list((await session.scalars(
        select(AttendanceModel).where(
            AttendanceModel.user_id == user_id,
            AttendanceModel.work_date.between(first_possible_date, today),
            AttendanceModel.record_status == "VALID",
            not_merged_source(),
        )
    )).all())
    records_by_date: dict[date, list[AttendanceModel]] = {}
    for record in records:
        records_by_date.setdefault(record.work_date, []).append(record)

    days: list[ReviewDay] = []
    work_date = today
    while work_date >= first_possible_date:
        status = await review_day_status(
            session, employee_id, work_date, records_by_date.get(work_date, []), now,
        )
        if status is None:
            if days:
                status = ReviewDayStatus.UNKNOWN
            else:
                work_date -= timedelta(days=1)
                continue
        days.append(ReviewDay(work_date, status))
        if status not in (ReviewDayStatus.ABSENT, ReviewDayStatus.REST_DAY, ReviewDayStatus.HOLIDAY):
            break
        work_date -= timedelta(days=1)
    return current_absence_streak(days)
