from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.domain.tardiness_screening import AttendanceDayFact, screen_tardiness
from app.attendance.infrastructure.attendance_merge_queries import not_merged_source
from app.attendance.infrastructure.correction_db_model import AttendanceCorrectionModel
from app.attendance.infrastructure.db_model import AttendanceModel
from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel
from app.filemaintenance.schedule.infrastructure.db_model import EmployeeScheduleAssignmentModel


class TardinessAttendanceRecord(BaseModel):
    attendance_id: UUID
    work_date: date
    expected_clock_in_at: datetime | None
    clock_in_at: datetime | None
    late_minutes: int
    attendance_mode: str


class TardinessReviewCandidate(BaseModel):
    employee_id: UUID
    employee_no: str
    employee_name: str
    late_dates: tuple[date, ...]
    duplicate_dates: tuple[date, ...]
    pending_correction_dates: tuple[date, ...]
    records: list[TardinessAttendanceRecord]


class TardinessReview(BaseModel):
    period_start: date
    period_end: date
    candidates: list[TardinessReviewCandidate]


async def load_tardiness_review(
    session: AsyncSession,
    period_start: date,
    period_end: date,
) -> TardinessReview:
    if period_end < period_start:
        raise ValueError("The screening period end must not precede its start.")

    assignment = EmployeeScheduleAssignmentModel
    attendance_mode = (
        select(assignment.attendance_mode)
        .where(
            assignment.employee_id == UserModel.employee_id,
            assignment.is_active.is_(True),
            assignment.status.in_(("ACTIVE", "APPROVED")),
            assignment.effective_from <= AttendanceModel.work_date,
            or_(assignment.effective_to.is_(None), assignment.effective_to >= AttendanceModel.work_date),
        )
        .order_by(assignment.effective_from.desc(), assignment.created_at.desc())
        .limit(1)
        .correlate(UserModel, AttendanceModel)
        .scalar_subquery()
    )
    statement = (
        select(
            EmployeeModel.id.label("employee_id"),
            EmployeeModel.employee_no,
            EmployeeModel.first_name,
            EmployeeModel.middle_name,
            EmployeeModel.last_name,
            EmployeeModel.suffix,
            EmployeeModel.preferred_name,
            AttendanceModel.id.label("attendance_id"),
            AttendanceModel.work_date,
            AttendanceModel.expected_clock_in_at,
            func.coalesce(AttendanceModel.corrected_clock_in_at, AttendanceModel.clock_in_at).label("clock_in_at"),
            AttendanceModel.late_minutes,
            func.coalesce(attendance_mode, "PUNCH_REQUIRED").label("attendance_mode"),
        )
        .select_from(AttendanceModel)
        .join(UserModel, UserModel.id == AttendanceModel.user_id)
        .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
        .where(
            AttendanceModel.work_date >= period_start,
            AttendanceModel.work_date <= period_end,
            AttendanceModel.record_status == "VALID",
            not_merged_source(),
        )
        .order_by(EmployeeModel.employee_no, AttendanceModel.work_date, AttendanceModel.id)
    )
    rows = (await session.execute(statement)).all()
    pending = (await session.execute(
        select(AttendanceCorrectionModel.employee_id, AttendanceCorrectionModel.work_date).where(
            AttendanceCorrectionModel.work_date >= period_start,
            AttendanceCorrectionModel.work_date <= period_end,
            AttendanceCorrectionModel.status == "PENDING",
        )
    )).all()

    facts: list[AttendanceDayFact] = []
    records_by_employee: dict[UUID, list[TardinessAttendanceRecord]] = {}
    employees: dict[UUID, tuple[str, str]] = {}
    for row in rows:
        late_minutes = 0 if row.attendance_mode == "SCHEDULE_CREDITED" else row.late_minutes
        facts.append(AttendanceDayFact(
            employee_id=row.employee_id,
            work_date=row.work_date,
            record_id=row.attendance_id,
            late_minutes=late_minutes,
        ))
        records_by_employee.setdefault(row.employee_id, []).append(TardinessAttendanceRecord(
            attendance_id=row.attendance_id,
            work_date=row.work_date,
            expected_clock_in_at=row.expected_clock_in_at,
            clock_in_at=row.clock_in_at,
            late_minutes=late_minutes,
            attendance_mode=row.attendance_mode,
        ))
        name = (row.preferred_name or "").strip() or " ".join(
            part for part in (row.first_name, row.middle_name, row.last_name, row.suffix) if part
        )
        employees[row.employee_id] = (row.employee_no, name)

    candidates = screen_tardiness(facts, [(row.employee_id, row.work_date) for row in pending], period_start, period_end)
    reviews = []
    for candidate in candidates:
        employee_no, name = employees[candidate.employee_id]
        reviews.append(TardinessReviewCandidate(
            employee_id=candidate.employee_id,
            employee_no=employee_no,
            employee_name=name,
            late_dates=candidate.late_dates,
            duplicate_dates=candidate.duplicate_dates,
            pending_correction_dates=candidate.pending_correction_dates,
            records=records_by_employee[candidate.employee_id],
        ))
    reviews.sort(key=lambda candidate: candidate.employee_no)
    return TardinessReview(period_start=period_start, period_end=period_end, candidates=reviews)
