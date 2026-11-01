from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.filemaintenance.employees.infrastructure.db_model import EmploymentAssignmentModel
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel

PH_TIMEZONE = ZoneInfo("Asia/Manila")
DeadlineStage = Literal["FILING", "APPROVAL"]


class CutoffDeadlineSource(Protocol):
    cutoff_code: str
    attendance_deadline: datetime | None
    attendance_finalized_at: datetime | None


class CutoffDeadlineError(ValueError):
    pass


def validate_attendance_deadline(period_end: date, deadline: datetime | None) -> None:
    """The deadline cannot close the cutoff before its last day has ended."""
    if deadline is None:
        return
    if deadline.tzinfo is None or deadline.utcoffset() is None:
        raise ValueError("Attendance deadlines must include a timezone.")
    last_day_end = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=PH_TIMEZONE)
    if deadline < last_day_end:
        raise ValueError("attendance_deadline must be after the last day of the cutoff period.")


def validate_cutoff_deadlines(
    period_end: date,
    attendance_deadline: datetime | None,
    employee_filing_deadline: datetime | None,
) -> None:
    validate_attendance_deadline(period_end, attendance_deadline)
    validate_attendance_deadline(period_end, employee_filing_deadline)
    if employee_filing_deadline is not None:
        if attendance_deadline is None:
            raise ValueError("Set the supervisor approval deadline when setting an employee filing deadline.")
        if employee_filing_deadline > attendance_deadline:
            raise ValueError("Employee filing deadline cannot be after the supervisor approval deadline.")


def _deadline(cutoff: CutoffDeadlineSource, stage: DeadlineStage) -> datetime | None:
    if stage == "FILING":
        filing_deadline = getattr(cutoff, "employee_filing_deadline", None)
        if filing_deadline is not None:
            return filing_deadline
    return cutoff.attendance_deadline


def is_cutoff_closed(
    cutoff: CutoffDeadlineSource,
    now: datetime | None = None,
    *,
    stage: DeadlineStage = "APPROVAL",
) -> bool:
    if getattr(cutoff, "attendance_finalized_at", None) is not None:
        return True
    if getattr(cutoff, "locked_at", None) is not None:
        return True
    if str(getattr(cutoff, "status", "") or "").upper() == "LOCKED":
        return True
    deadline = _deadline(cutoff, stage)
    return deadline is not None and (now or datetime.now(timezone.utc)) > deadline


def require_cutoff_open(
    cutoff: CutoffDeadlineSource | None,
    now: datetime | None = None,
    *,
    stage: DeadlineStage = "APPROVAL",
) -> None:
    """Attendance covered by a lapsed or approved cutoff cannot be filed, changed or approved."""
    if cutoff is None or not is_cutoff_closed(cutoff, now, stage=stage):
        return
    if getattr(cutoff, "attendance_finalized_at", None) is not None:
        raise CutoffDeadlineError(
            f"Attendance for payroll cutoff {cutoff.cutoff_code} has been finalized. "
            "Attendance covered by this cutoff can no longer be changed."
        )
    deadline = _deadline(cutoff, stage)
    if deadline is not None and (now or datetime.now(timezone.utc)) > deadline:
        label = (
            "employee filing"
            if stage == "FILING" and getattr(cutoff, "employee_filing_deadline", None) is not None
            else "attendance"
        )
        raise CutoffDeadlineError(
            f"The {label} deadline for payroll cutoff {cutoff.cutoff_code} passed on "
            f"{deadline.astimezone(PH_TIMEZONE):%b %d, %Y %I:%M %p}. "
            "Attendance covered by this cutoff can no longer be changed."
        )
    raise CutoffDeadlineError(
        f"Payroll cutoff {cutoff.cutoff_code} is already approved. "
        "Attendance covered by this cutoff can no longer be changed."
    )


async def require_attendance_open(
    session: AsyncSession,
    employee_id: UUID,
    start_date: date,
    end_date: date,
    now: datetime | None = None,
    *,
    stage: DeadlineStage = "APPROVAL",
    lock_for_update: bool = False,
) -> list[PayrollCutoffModel]:
    if end_date < start_date:
        raise ValueError("The request end date cannot be before its start date.")

    statement = (
        select(PayrollCutoffModel, EmploymentAssignmentModel)
        .join(
            EmploymentAssignmentModel,
            EmploymentAssignmentModel.payroll_group_id
            == PayrollCutoffModel.payroll_group_id,
        )
        .where(
            EmploymentAssignmentModel.employee_id == employee_id,
            EmploymentAssignmentModel.is_active.is_(True),
            EmploymentAssignmentModel.status == "ACTIVE",
            EmploymentAssignmentModel.effective_from <= end_date,
            or_(
                EmploymentAssignmentModel.effective_to.is_(None),
                EmploymentAssignmentModel.effective_to >= start_date,
            ),
            or_(
                EmploymentAssignmentModel.separation_date.is_(None),
                EmploymentAssignmentModel.separation_date >= start_date,
            ),
            PayrollCutoffModel.is_active.is_(True),
            PayrollCutoffModel.period_start <= end_date,
            PayrollCutoffModel.period_end >= start_date,
        )
    )
    if lock_for_update:
        statement = statement.order_by(PayrollCutoffModel.id).with_for_update(of=PayrollCutoffModel)
    rows = (await session.execute(statement)).all()
    applicable: dict[UUID, PayrollCutoffModel] = {}

    for cutoff, assignment in rows:
        overlap_start = max(start_date, cutoff.period_start, assignment.effective_from)
        overlap_end = min(
            end_date,
            cutoff.period_end,
            assignment.effective_to or end_date,
            assignment.separation_date or end_date,
        )
        if overlap_start <= overlap_end:
            applicable[cutoff.id] = cutoff

    for cutoff in applicable.values():
        require_cutoff_open(cutoff, now, stage=stage)
    return list(applicable.values())
