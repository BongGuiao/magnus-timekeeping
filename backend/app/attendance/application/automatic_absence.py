import logging
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.application.use_case import (
    lock_attendance_user,
    resolve_attendance_day_type,
    resolve_schedule_day,
)
from app.attendance.domain.worked_minutes import requires_scheduled_work
from app.attendance.domain.automatic_absence import AUTO_ABSENCE_KEY, has_automatic_absence_marker
from app.attendance.infrastructure.attendance_merge_queries import not_merged_source
from app.attendance.infrastructure.db_model import AttendanceModel, OfficialBusinessRequestModel
from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import LeaveApplicationModel
from app.filemaintenance.payroll_cutoffs.application.deadline_policy import (
    CutoffDeadlineError,
    require_attendance_open,
)
from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import (
    EmployeeCutoffResultModel,
)
from app.filemaintenance.schedule.infrastructure.db_model import EmployeeScheduleAssignmentModel
from app.filemaintenance.schedule.infrastructure.emergency_schedule_db_model import EmergencyScheduleRequestModel

logger = logging.getLogger(__name__)
MANILA = ZoneInfo("Asia/Manila")
ABSENCE_DELAY = timedelta(minutes=60)


def _void_absence(record: AttendanceModel, now: datetime, reason: str) -> None:
    metadata = dict(record.punch_metadata or {})
    metadata[AUTO_ABSENCE_KEY] = {
        **metadata[AUTO_ABSENCE_KEY],
        "cleared_at": now.isoformat(),
        "clear_reason": reason,
    }
    record.punch_metadata = metadata
    record.is_absent = False
    record.record_status = "VOID"


async def _has_approved_exception(
    session: AsyncSession, employee_id: UUID, work_date: date, shift_end: datetime,
) -> bool:
    start = datetime.combine(work_date, time.min, tzinfo=MANILA)
    end = max(datetime.combine(work_date + timedelta(days=1), time.min, tzinfo=MANILA), shift_end)
    for model in (LeaveApplicationModel, OfficialBusinessRequestModel):
        found = await session.scalar(select(model.id).where(
            model.employee_id == employee_id,
            model.is_active.is_(True),
            model.status == "APPROVED",
            model.start_at < end,
            model.end_at > start,
        ).limit(1))
        if found is not None:
            return True
    return False


async def _payroll_is_open(
    session: AsyncSession, employee_id: UUID, work_date: date, now: datetime,
) -> bool:
    try:
        cutoffs = await require_attendance_open(
            session, employee_id, work_date, work_date, now, lock_for_update=True,
        )
    except CutoffDeadlineError as error:
        logger.info("Skipping automatic absence for employee %s on %s: %s", employee_id, work_date, error)
        return False
    for cutoff in cutoffs:
        if cutoff.status.upper() not in ("SCHEDULED", "OPEN") or cutoff.export_batch_id is not None:
            return False
        if await session.scalar(select(EmployeeCutoffResultModel.id).where(
            EmployeeCutoffResultModel.cutoff_id == cutoff.id,
            EmployeeCutoffResultModel.employee_id == employee_id,
        ).limit(1)):
            return False
    return True


async def process_automatic_absence(
    session: AsyncSession, user_id: UUID, employee_id: UUID, work_date: date, now: datetime,
) -> str:
    """Reconcile a single employee-day while holding the same account lock as clock-in."""
    await lock_attendance_user(session, user_id, employee_id)
    if not await _payroll_is_open(session, employee_id, work_date, now):
        return "payroll_closed"

    records = list((await session.scalars(select(AttendanceModel).where(
        AttendanceModel.user_id == user_id,
        AttendanceModel.work_date == work_date,
        not_merged_source(),
    ))).all())
    generated = [
        row for row in records
        if has_automatic_absence_marker(row.punch_metadata) and row.is_absent and row.record_status == "VALID"
    ]
    valid_punch = any(
        row.record_status == "VALID" and (row.clock_in_at or row.corrected_clock_in_at)
        and row not in generated
        for row in records
    )
    if generated:
        exception = await _has_approved_exception(
            session, employee_id, work_date,
            max(row.expected_clock_out_at for row in generated if row.expected_clock_out_at is not None),
        )
        if valid_punch or exception:
            cleared = False
            for row in generated:
                if row.is_locked:
                    logger.warning("Cannot clear locked automatic absence %s", row.id)
                    continue
                _void_absence(row, now, "clock_in" if valid_punch else "approved_leave_or_official_business")
                cleared = True
            return "cleared" if cleared else "locked"
        if work_date >= now.astimezone(MANILA).date() - timedelta(days=1):
            schedule = await resolve_schedule_day(session, employee_id, work_date)
            day_type = await resolve_attendance_day_type(session, employee_id, work_date)
            eligible = (
                schedule.schedule_template_id is not None
                and schedule.attendance_mode == "PUNCH_REQUIRED"
                and schedule.expected_clock_in_at is not None
                and schedule.expected_clock_out_at is not None
                and bool(schedule.schedule_context)
                and requires_scheduled_work(schedule.work_type, day_type)
                and now >= schedule.expected_clock_in_at + ABSENCE_DELAY
            )
            changed = False
            for row in generated:
                if row.is_locked:
                    logger.warning("Cannot reconcile locked automatic absence %s", row.id)
                    continue
                if not eligible:
                    _void_absence(row, now, "schedule_changed")
                    changed = True
                    continue
                metadata = dict(row.punch_metadata or {})
                if (
                    row.schedule_template_id == schedule.schedule_template_id
                    and row.expected_clock_in_at == schedule.expected_clock_in_at
                    and row.expected_clock_out_at == schedule.expected_clock_out_at
                    and row.work_type == schedule.work_type
                    and row.day_type == day_type
                    and metadata.get("schedule_context") == schedule.schedule_context
                ):
                    continue
                row.schedule_template_id = schedule.schedule_template_id
                row.expected_clock_in_at = schedule.expected_clock_in_at
                row.expected_clock_out_at = schedule.expected_clock_out_at
                row.work_type = schedule.work_type
                row.day_type = day_type
                row.punch_metadata = {
                    **metadata,
                    "schedule_context": schedule.schedule_context,
                }
                changed = True
            if changed:
                return "updated_schedule" if eligible else "cleared_schedule"
        return "already_recorded"

    if any(
        row.record_status != "INVALID" or not (row.clock_in_at or row.corrected_clock_in_at)
        for row in records
    ):
        return "attendance_exists"
    employment = await session.scalar(select(EmploymentAssignmentModel.id).where(
        EmploymentAssignmentModel.employee_id == employee_id,
        EmploymentAssignmentModel.is_active.is_(True),
        EmploymentAssignmentModel.status == "ACTIVE",
        EmploymentAssignmentModel.effective_from <= work_date,
        or_(EmploymentAssignmentModel.effective_to.is_(None), EmploymentAssignmentModel.effective_to >= work_date),
        or_(EmploymentAssignmentModel.separation_date.is_(None), EmploymentAssignmentModel.separation_date >= work_date),
    ).limit(1))
    if employment is None:
        return "no_employment"
    schedule = await resolve_schedule_day(session, employee_id, work_date)
    if (
        schedule.schedule_template_id is None
        or schedule.attendance_mode != "PUNCH_REQUIRED"
        or schedule.expected_clock_in_at is None
        or schedule.expected_clock_out_at is None
        or not schedule.schedule_context
    ):
        return "no_punch_schedule"
    day_type = await resolve_attendance_day_type(session, employee_id, work_date)
    if not requires_scheduled_work(schedule.work_type, day_type):
        return "nonworking_day"
    if now < schedule.expected_clock_in_at + ABSENCE_DELAY:
        return "not_due"
    if await _has_approved_exception(session, employee_id, work_date, schedule.expected_clock_out_at):
        return "approved_exception"
    session.add(AttendanceModel(
        user_id=user_id,
        work_date=work_date,
        schedule_template_id=schedule.schedule_template_id,
        expected_clock_in_at=schedule.expected_clock_in_at,
        expected_clock_out_at=schedule.expected_clock_out_at,
        work_type=schedule.work_type,
        day_type=day_type,
        is_absent=True,
        record_status="VALID",
        punch_metadata={
            "schedule_context": schedule.schedule_context,
            AUTO_ABSENCE_KEY: {"recorded_at": now.isoformat(), "delay_minutes": 60},
        },
    ))
    await session.flush()
    return "created"


async def active_employee_accounts(
    session: AsyncSession, start: date, end: date,
) -> list[tuple[UUID, UUID]]:
    employment = exists(select(EmploymentAssignmentModel.id).where(
        EmploymentAssignmentModel.employee_id == EmployeeModel.id,
        EmploymentAssignmentModel.is_active.is_(True),
        EmploymentAssignmentModel.status == "ACTIVE",
        EmploymentAssignmentModel.effective_from <= end,
        or_(EmploymentAssignmentModel.effective_to.is_(None), EmploymentAssignmentModel.effective_to >= start),
        or_(EmploymentAssignmentModel.separation_date.is_(None), EmploymentAssignmentModel.separation_date >= start),
    ))
    assignment = exists(select(EmployeeScheduleAssignmentModel.id).where(
        EmployeeScheduleAssignmentModel.employee_id == EmployeeModel.id,
        EmployeeScheduleAssignmentModel.is_active.is_(True),
        EmployeeScheduleAssignmentModel.status == "APPROVED",
        EmployeeScheduleAssignmentModel.effective_from <= end,
        or_(EmployeeScheduleAssignmentModel.effective_to.is_(None), EmployeeScheduleAssignmentModel.effective_to >= start),
    ))
    emergency = exists(select(EmergencyScheduleRequestModel.id).where(
        EmergencyScheduleRequestModel.employee_id == EmployeeModel.id,
        EmergencyScheduleRequestModel.status == "APPROVED",
        EmergencyScheduleRequestModel.work_date >= start,
        EmergencyScheduleRequestModel.work_date <= end,
    ))
    return list((await session.execute(
        select(UserModel.id, EmployeeModel.id)
        .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
        .where(
            UserModel.is_active.is_(True), UserModel.account_status == "ACTIVE",
            EmployeeModel.is_active.is_(True), EmployeeModel.record_status == "ACTIVE",
            employment, or_(assignment, emergency),
        )
    )).all())
