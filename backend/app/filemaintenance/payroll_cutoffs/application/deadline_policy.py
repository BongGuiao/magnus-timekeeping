from datetime import date, datetime, timezone
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.filemaintenance.employees.infrastructure.db_model import EmploymentAssignmentModel
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel

CutoffPhase = Literal["EMPLOYEE", "SUPERVISOR", "HR"]


class CutoffDeadlineSource(Protocol):
    cutoff_code: str
    employee_review_deadline: datetime | None
    supervisor_deadline: datetime | None
    hr_deadline: datetime | None


_DEADLINE_FIELDS: dict[CutoffPhase, str] = {
    "EMPLOYEE": "employee_review_deadline",
    "SUPERVISOR": "supervisor_deadline",
    "HR": "hr_deadline",
}


class CutoffDeadlineError(ValueError):
    pass


def require_cutoff_phase_open(
    cutoff: CutoffDeadlineSource | None,
    phase: CutoffPhase,
    now: datetime | None = None,
) -> None:
    if cutoff is None:
        return
    deadline = getattr(cutoff, _DEADLINE_FIELDS[phase])
    current_time = now or datetime.now(timezone.utc)
    if deadline is not None and current_time > deadline:
        phase_name = "employee filing" if phase == "EMPLOYEE" else (
            "supervisor review" if phase == "SUPERVISOR" else "HR processing"
        )
        raise CutoffDeadlineError(
            f"The {phase_name} deadline for payroll cutoff {cutoff.cutoff_code} "
            f"has passed ({deadline.isoformat()})."
        )


async def require_employee_phase_open(
    session: AsyncSession,
    employee_id: UUID,
    start_date: date,
    end_date: date,
    phase: CutoffPhase,
    now: datetime | None = None,
) -> None:
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
        require_cutoff_phase_open(cutoff, phase, now)
