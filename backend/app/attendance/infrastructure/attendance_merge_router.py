from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, or_, select

from app.attendance.application.use_case import (
    PH_TIMEZONE,
    calculate_attendance_metrics,
    calculate_break_policy,
    calculate_net_nonpayable_break_minutes,
    calculate_night_differential_minutes,
    calculate_overtime_breakdown,
    to_utc,
)
from app.attendance.infrastructure.db_model import (
    AttendanceMergeModel,
    AttendanceMergeSourceModel,
    AttendanceModel,
    OvertimeApplicationModel,
)
from app.attendance.infrastructure.overtime_adapters import queue_recent_attendance_refresh
from app.auth.infrastructure.db_model import UserModel
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.payroll_cutoffs.application.deadline_policy import (
    CutoffDeadlineError,
    require_attendance_open,
)
from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import (
    EmployeeCutoffResultModel,
)
from app.filemaintenance.schedule.infrastructure.db_model import (
    ScheduleSegmentModel,
    ScheduleTemplateModel,
)

router = APIRouter(prefix="/attendance-merges", tags=["Attendance Merge"])
MAX_REASON_LENGTH = 1000
BREAK_FIELDS = (
    "first_break_out_at",
    "first_break_in_at",
    "meal_break_out_at",
    "meal_break_in_at",
    "second_break_out_at",
    "second_break_in_at",
    "ot_break_out_at",
    "ot_break_in_at",
)


class ScheduleTemplateOption(BaseModel):
    id: UUID
    schedule_code: str
    schedule_name: str


class CreateAttendanceMergeRequest(BaseModel):
    source_attendance_ids: list[UUID] = Field(min_length=2, max_length=10)
    schedule_template_id: UUID
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    verified_clock_out_at: datetime | None = None

    @field_validator("verified_clock_out_at")
    @classmethod
    def require_timezone_for_verified_clock_out(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("The verified clock-out must include a timezone.")
        return value


class AttendanceMergeSourceAudit(BaseModel):
    source_attendance_id: UUID
    source_snapshot: dict[str, Any]


class AttendanceMergeAudit(BaseModel):
    merge_id: UUID
    canonical_attendance_id: UUID
    employee_id: UUID
    work_date: date
    schedule_template_id: UUID
    schedule_code: str
    merged_by: UUID | None
    merged_at: datetime
    reason: str
    canonical_clock_in_at: datetime
    canonical_clock_out_at: datetime
    calculation_snapshot: dict[str, Any]
    sources: list[AttendanceMergeSourceAudit]


class AttendanceMergeResult(BaseModel):
    merge_id: UUID
    canonical_attendance_id: UUID
    employee_id: UUID
    work_date: date
    clock_in_at: datetime
    clock_out_at: datetime
    schedule_code: str


def _require_hr_admin(claims: dict[str, Any]) -> UUID:
    role_codes = claims.get("role_codes", claims.get("roles", []))
    if not isinstance(role_codes, list) or not any(
        isinstance(role, str) and role.strip().upper() == "HR_ADMIN"
        for role in role_codes
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only HR Admins may merge attendance records or view merge audits.",
        )
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in authentication token.",
        ) from error


def _active_employment_conditions(work_date: date):
    return (
        EmploymentAssignmentModel.is_active.is_(True),
        EmploymentAssignmentModel.status == "ACTIVE",
        EmploymentAssignmentModel.effective_from <= work_date,
        or_(
            EmploymentAssignmentModel.effective_to.is_(None),
            EmploymentAssignmentModel.effective_to >= work_date,
        ),
        or_(
            EmploymentAssignmentModel.separation_date.is_(None),
            EmploymentAssignmentModel.separation_date >= work_date,
        ),
    )


async def _employee_for_attendance(session, attendance_id: UUID):
    row = (
        await session.execute(
            select(AttendanceModel, UserModel.employee_id)
            .join(UserModel, UserModel.id == AttendanceModel.user_id)
            .where(AttendanceModel.id == attendance_id)
        )
    ).first()
    if row is None or row[1] is None:
        raise HTTPException(status_code=404, detail="Attendance record or employee profile not found.")
    return row[0], row[1]


async def _active_schedule_template(
    session,
    employee_id: UUID,
    work_date: date,
    template_id: UUID,
) -> tuple[ScheduleTemplateModel, list[ScheduleSegmentModel]]:
    company_ids = set(
        (
            await session.scalars(
                select(EmploymentAssignmentModel.company_id)
                .where(
                    EmploymentAssignmentModel.employee_id == employee_id,
                    *_active_employment_conditions(work_date),
                )
                .distinct()
            )
        ).all()
    )
    if not company_ids:
        raise HTTPException(
            status_code=409,
            detail="No active employment assignment covers the attendance work date.",
        )
    template = await session.scalar(
        select(ScheduleTemplateModel).where(
            ScheduleTemplateModel.id == template_id,
            ScheduleTemplateModel.company_id.in_(company_ids),
            ScheduleTemplateModel.is_active.is_(True),
            ScheduleTemplateModel.status == "ACTIVE",
            ScheduleTemplateModel.effective_from <= work_date,
            or_(
                ScheduleTemplateModel.effective_to.is_(None),
                ScheduleTemplateModel.effective_to >= work_date,
            ),
        )
    )
    if template is None:
        raise HTTPException(
            status_code=422,
            detail="Choose an active schedule template valid for the employee and work date.",
        )
    segments = list(
        (
            await session.scalars(
                select(ScheduleSegmentModel)
                .where(ScheduleSegmentModel.schedule_template_id == template.id)
                .order_by(ScheduleSegmentModel.segment_sequence)
            )
        ).all()
    )
    if not any(segment.segment_type == "WORK" for segment in segments):
        raise HTTPException(status_code=422, detail="The selected schedule has no work segments.")
    return template, segments


def _source_snapshot(record: AttendanceModel) -> dict[str, Any]:
    fields = (
        "work_date",
        "clock_in_at",
        "clock_out_at",
        "corrected_clock_in_at",
        "corrected_clock_out_at",
        "expected_clock_in_at",
        "expected_clock_out_at",
        "schedule_template_id",
        "record_status",
        "is_locked",
        *BREAK_FIELDS,
        "created_at",
        "updated_at",
    )
    snapshot: dict[str, Any] = {}
    for field in fields:
        value = getattr(record, field)
        if isinstance(value, (datetime, date)):
            snapshot[field] = value.isoformat()
        elif isinstance(value, UUID):
            snapshot[field] = str(value)
        else:
            snapshot[field] = value
    return snapshot


def _effective_punch(record: AttendanceModel, field: str) -> datetime | None:
    corrected = getattr(record, f"corrected_{field}")
    return corrected or getattr(record, field)


def _merged_punches(
    records: list[AttendanceModel],
    verified_clock_out_at: datetime | None = None,
) -> tuple[datetime, datetime]:
    starts = [
        (record, punch)
        for record in records
        if (punch := _effective_punch(record, "clock_in_at")) is not None
    ]
    ends = [
        punch for record in records
        if (punch := _effective_punch(record, "clock_out_at")) is not None
    ]
    if not starts:
        raise HTTPException(
            status_code=409,
            detail="The source records must collectively contain a clock-in and a clock-out.",
        )
    latest_start_at = max((punch for _, punch in starts), key=to_utc)
    latest_sequences = [
        record
        for record, punch in starts
        if to_utc(punch) == to_utc(latest_start_at)
    ]
    latest_sequence_missing_clock_out = any(
        _effective_punch(record, "clock_out_at") is None
        for record in latest_sequences
    )
    if latest_sequence_missing_clock_out and verified_clock_out_at is None:
        raise HTTPException(
            status_code=409,
            detail="Enter the HR-verified actual clock-out for the latest source sequence before merging.",
        )
    if not latest_sequence_missing_clock_out and verified_clock_out_at is not None:
        raise HTTPException(
            status_code=422,
            detail="A verified clock-out may only be supplied when the latest source sequence is missing one.",
        )
    if not ends:
        if verified_clock_out_at is None:
            raise HTTPException(
                status_code=409,
                detail="The source records must collectively contain a clock-in and a clock-out.",
            )
    if verified_clock_out_at is not None:
        if verified_clock_out_at.tzinfo is None or verified_clock_out_at.utcoffset() is None:
            raise HTTPException(status_code=422, detail="The verified clock-out must include a timezone.")
        if to_utc(verified_clock_out_at) <= to_utc(latest_start_at):
            raise HTTPException(
                status_code=422,
                detail="The verified clock-out must be after the latest source clock-in.",
            )
        if to_utc(verified_clock_out_at) > datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="The verified clock-out cannot be in the future.")
        if ends and to_utc(verified_clock_out_at) < max(map(to_utc, ends)):
            raise HTTPException(
                status_code=422,
                detail="The verified clock-out cannot be earlier than another recorded source clock-out.",
            )
    actual_start = min((punch for _, punch in starts), key=to_utc)
    actual_end = verified_clock_out_at or max(ends, key=to_utc)
    if to_utc(actual_end) <= to_utc(actual_start):
        raise HTTPException(
            status_code=409,
            detail="The merged clock-out must be after the merged clock-in.",
        )
    return actual_start, actual_end


async def _require_open_unprocessed_cutoff(session, employee_id: UUID, work_date: date) -> None:
    try:
        cutoffs = await require_attendance_open(
            session,
            employee_id,
            work_date,
            work_date,
            datetime.now(timezone.utc),
            lock_for_update=True,
        )
    except CutoffDeadlineError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if len(cutoffs) != 1:
        raise HTTPException(
            status_code=409,
            detail="A single active, open payroll cutoff must cover the attendance date.",
        )
    cutoff = cutoffs[0]
    processed = await session.scalar(
        select(EmployeeCutoffResultModel.id)
        .where(EmployeeCutoffResultModel.cutoff_id == cutoff.id)
        .limit(1)
    )
    if (
        processed is not None
        or cutoff.export_batch_id is not None
        or cutoff.attendance_finalized_at is not None
        or cutoff.locked_at is not None
        or cutoff.status.strip().upper() in {"LOCKED", "CLOSED", "PROCESSED", "FINALIZED"}
    ):
        raise HTTPException(
            status_code=409,
            detail="Attendance cannot be merged after the payroll cutoff has been processed or closed.",
        )


def _break_values(records: list[AttendanceModel]) -> dict[str, datetime | None]:
    values: dict[str, datetime | None] = {}
    for field in BREAK_FIELDS:
        unique_values = {getattr(record, field) for record in records if getattr(record, field) is not None}
        if len(unique_values) > 1:
            raise HTTPException(
                status_code=409,
                detail=f"Source attendance records have conflicting {field.replace('_', ' ')} punches.",
            )
        values[field] = next(iter(unique_values), None)
    return values


def _apply_schedule_calculations(
    canonical: AttendanceModel,
    template: ScheduleTemplateModel,
    segments: list[ScheduleSegmentModel],
    work_date: date,
) -> None:
    work_segments = [segment for segment in segments if segment.segment_type == "WORK"]
    first_segment, last_segment = work_segments[0], work_segments[-1]
    expected_start = datetime.combine(work_date, first_segment.start_time, tzinfo=PH_TIMEZONE)
    expected_end = datetime.combine(
        work_date + timedelta(days=last_segment.end_day_offset),
        last_segment.end_time,
        tzinfo=PH_TIMEZONE,
    )
    if to_utc(expected_end) <= to_utc(expected_start):
        raise HTTPException(status_code=422, detail="The selected schedule has invalid work segment times.")

    break_segments = [segment for segment in segments if segment.break_slot is not None]
    break_rules = [
        {
            "segment_id": str(segment.id),
            "break_slot": segment.break_slot,
            "segment_type": segment.segment_type,
            "break_minutes": segment.break_minutes,
            "auto_deduct": segment.auto_deduct,
            "start_at": datetime.combine(
                work_date, segment.start_time, tzinfo=PH_TIMEZONE,
            ).isoformat(),
            "end_at": datetime.combine(
                work_date + timedelta(days=segment.end_day_offset),
                segment.end_time,
                tzinfo=PH_TIMEZONE,
            ).isoformat(),
        }
        for segment in break_segments
    ]
    context = {
        "schedule_template_id": str(template.id),
        "grace_minutes": template.grace_minutes,
        "ot_eligible": template.ot_eligible,
        "minimum_ot_minutes": template.minimum_ot_minutes,
        "pre_shift_ot_allowed": template.pre_shift_ot_allowed,
        "early_clock_in_allowance_minutes": first_segment.flex_start_minutes,
        "break_rules": break_rules,
        "recalculation_baseline_expected_clock_in_at": expected_start.isoformat(),
        "recalculation_baseline_expected_clock_out_at": expected_end.isoformat(),
    }
    metadata = dict(canonical.punch_metadata or {})
    metadata["schedule_context"] = context
    canonical.schedule_template_id = template.id
    canonical.expected_clock_in_at = expected_start
    canonical.expected_clock_out_at = expected_end
    canonical.work_type = "REG"
    canonical.punch_metadata = metadata

    actual_start = canonical.corrected_clock_in_at or canonical.clock_in_at
    actual_end = canonical.corrected_clock_out_at or canonical.clock_out_at
    try:
        break_excess, unpaid_break, break_intervals = calculate_break_policy(
            canonical, break_rules,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"Selected schedule break policy cannot be calculated: {error}") from error

    regular_ot, night_ot, total_ot = calculate_overtime_breakdown(
        expected_clock_in_at=expected_start,
        expected_clock_out_at=expected_end,
        actual_clock_in_at=actual_start,
        actual_clock_out_at=actual_end,
        ot_eligible=template.ot_eligible,
        minimum_ot_minutes=template.minimum_ot_minutes,
        pre_shift_ot_allowed=template.pre_shift_ot_allowed,
        break_intervals=break_intervals,
    )
    late, undertime, _ = calculate_attendance_metrics(
        expected_clock_in_at=expected_start,
        expected_clock_out_at=expected_end,
        actual_clock_in_at=actual_start,
        actual_clock_out_at=actual_end,
        grace_minutes=template.grace_minutes,
        ot_eligible=template.ot_eligible,
        minimum_ot_minutes=template.minimum_ot_minutes,
        pre_shift_ot_allowed=template.pre_shift_ot_allowed,
        break_intervals=break_intervals,
    )
    night_minutes = calculate_night_differential_minutes(
        actual_clock_in_at=actual_start,
        actual_clock_out_at=actual_end,
        break_intervals=break_intervals,
    )
    net_break_minutes = calculate_net_nonpayable_break_minutes(
        canonical,
        break_rules,
        break_intervals,
        actual_start,
        actual_end,
    )
    worked_minutes = max(
        int((to_utc(actual_end) - to_utc(actual_start)).total_seconds() // 60)
        - net_break_minutes,
        0,
    )
    canonical.late_minutes = late
    canonical.undertime_minutes = undertime
    canonical.calculated_ot_minutes = total_ot
    canonical.overtime_hours = Decimal(total_ot) / Decimal(60)
    canonical.regular_overtime_minutes = regular_ot
    canonical.regular_overtime_hours = Decimal(regular_ot) / Decimal(60)
    canonical.night_differential_overtime_minutes = night_ot
    canonical.night_differential_overtime_hours = Decimal(night_ot) / Decimal(60)
    canonical.night_differential_minutes = night_minutes
    canonical.night_differential_hours = Decimal(night_minutes) / Decimal(60)
    canonical.approved_night_differential_minutes = night_minutes
    canonical.approved_night_diff = night_minutes / 60
    canonical.approved_hours_worked = worked_minutes / 60
    metadata["break_calculation"] = {
        "excess_undertime_minutes": break_excess,
        "excess_minutes_break": break_excess,
        "unpaid_break_minutes": unpaid_break,
        "net_nonpayable_minutes": net_break_minutes,
        "undertime_excludes_break_excess": True,
    }
    canonical.punch_metadata = metadata


@router.get(
    "/schedule-templates",
    response_model=ResponseEnvelope[list[ScheduleTemplateOption]],
)
async def list_merge_schedule_templates(
    attendance_id: UUID = Query(...),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    _require_hr_admin(claims)
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        record, employee_id = await _employee_for_attendance(session, attendance_id)
        companies = select(EmploymentAssignmentModel.company_id).where(
            EmploymentAssignmentModel.employee_id == employee_id,
            *_active_employment_conditions(record.work_date),
        )
        templates = (
            await session.scalars(
                select(ScheduleTemplateModel)
                .where(
                    ScheduleTemplateModel.company_id.in_(companies),
                    ScheduleTemplateModel.is_active.is_(True),
                    ScheduleTemplateModel.status == "ACTIVE",
                    ScheduleTemplateModel.effective_from <= record.work_date,
                    or_(
                        ScheduleTemplateModel.effective_to.is_(None),
                        ScheduleTemplateModel.effective_to >= record.work_date,
                    ),
                    exists(
                        select(1).where(
                            ScheduleSegmentModel.schedule_template_id == ScheduleTemplateModel.id,
                            ScheduleSegmentModel.segment_type == "WORK",
                        )
                    ),
                )
                .order_by(ScheduleTemplateModel.schedule_code)
            )
        ).all()
        return ResponseEnvelope(
            status="success",
            data=[
                ScheduleTemplateOption(
                    id=template.id,
                    schedule_code=template.schedule_code,
                    schedule_name=template.schedule_name,
                )
                for template in templates
            ],
        )


@router.post(
    "",
    response_model=ResponseEnvelope[AttendanceMergeResult],
    status_code=status.HTTP_201_CREATED,
)
async def create_attendance_merge(
    payload: CreateAttendanceMergeRequest,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    actor_id = _require_hr_admin(claims)
    if len(set(payload.source_attendance_ids)) != len(payload.source_attendance_ids):
        raise HTTPException(status_code=422, detail="Source attendance ids must be unique.")
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Provide a reason for merging the attendance records.")

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        sources = list(
            (
                await session.scalars(
                    select(AttendanceModel)
                    .where(AttendanceModel.id.in_(payload.source_attendance_ids))
                    .order_by(AttendanceModel.id)
                    .with_for_update()
                )
            ).all()
        )
        if len(sources) != len(payload.source_attendance_ids):
            raise HTTPException(status_code=404, detail="One or more source attendance records were not found.")
        if len({record.user_id for record in sources}) != 1 or len({record.work_date for record in sources}) != 1:
            raise HTTPException(
                status_code=422,
                detail="All source records must belong to the same employee and work date.",
            )
        if any(record.record_status != "VALID" for record in sources):
            raise HTTPException(status_code=409, detail="Only valid source attendance records can be merged.")
        if any(record.is_locked for record in sources):
            raise HTTPException(status_code=409, detail="Locked attendance records cannot be merged.")
        source_ids = [record.id for record in sources]
        already_linked = await session.scalar(
            select(AttendanceMergeSourceModel.source_attendance_id)
            .where(AttendanceMergeSourceModel.source_attendance_id.in_(source_ids))
            .limit(1)
        )
        if already_linked is not None:
            raise HTTPException(status_code=409, detail="A source record has already been included in a merge.")
        employee_id = await session.scalar(
            select(UserModel.employee_id).where(UserModel.id == sources[0].user_id)
        )
        if employee_id is None:
            raise HTTPException(status_code=409, detail="The employee profile is missing.")
        work_date = sources[0].work_date
        await session.execute(
            select(EmployeeModel.id)
            .where(EmployeeModel.id == employee_id)
            .with_for_update()
        )
        existing_merge = await session.scalar(
            select(AttendanceMergeModel.id).where(
                AttendanceMergeModel.employee_id == employee_id,
                AttendanceMergeModel.work_date == work_date,
            )
        )
        if existing_merge is not None:
            raise HTTPException(status_code=409, detail="A canonical attendance merge already exists for this date.")
        await _require_open_unprocessed_cutoff(session, employee_id, work_date)

        overtime_application_id = await session.scalar(
            select(OvertimeApplicationModel.id)
            .where(OvertimeApplicationModel.attendance_record_id.in_(source_ids))
            .limit(1)
        )
        if overtime_application_id is not None:
            raise HTTPException(
                status_code=409,
                detail="Source attendance has an overtime application. Resolve it before merging.",
            )

        actual_start, actual_end = _merged_punches(
            sources,
            payload.verified_clock_out_at,
        )

        template, segments = await _active_schedule_template(
            session, employee_id, work_date, payload.schedule_template_id,
        )
        merge_id = uuid4()
        canonical_id = uuid4()
        metadata = {
            "attendance_merge": {
                "merge_id": str(merge_id),
                "source_attendance_ids": [str(source_id) for source_id in source_ids],
                **(
                    {"hr_verified_clock_out_at": payload.verified_clock_out_at.isoformat()}
                    if payload.verified_clock_out_at is not None
                    else {}
                ),
            }
        }
        canonical = AttendanceModel(
            id=canonical_id,
            user_id=sources[0].user_id,
            work_date=work_date,
            corrected_clock_in_at=actual_start,
            corrected_clock_out_at=actual_end,
            **_break_values(sources),
            work_type="REG",
            day_type=sources[0].day_type,
            record_status="VALID",
            is_manual_entry=True,
            is_locked=False,
            punch_metadata=metadata,
            created_by=actor_id,
            updated_by=actor_id,
        )
        _apply_schedule_calculations(canonical, template, segments, work_date)
        calculation_snapshot = {
            "expected_clock_in_at": canonical.expected_clock_in_at.isoformat(),
            "expected_clock_out_at": canonical.expected_clock_out_at.isoformat(),
            "late_minutes": canonical.late_minutes,
            "undertime_minutes": canonical.undertime_minutes,
            "worked_hours": canonical.approved_hours_worked,
            "regular_overtime_minutes": canonical.regular_overtime_minutes,
            "night_differential_overtime_minutes": canonical.night_differential_overtime_minutes,
            "total_overtime_minutes": canonical.calculated_ot_minutes,
            "night_differential_minutes": canonical.night_differential_minutes,
            **(
                {"hr_verified_clock_out_at": payload.verified_clock_out_at.isoformat()}
                if payload.verified_clock_out_at is not None
                else {}
            ),
        }
        session.add(canonical)
        await session.flush()

        merge = AttendanceMergeModel(
            id=merge_id,
            canonical_attendance_id=canonical.id,
            employee_id=employee_id,
            work_date=work_date,
            schedule_template_id=template.id,
            canonical_clock_in_at=actual_start,
            canonical_clock_out_at=actual_end,
            calculation_snapshot=calculation_snapshot,
            merged_by=actor_id,
            reason=reason,
        )
        session.add(merge)
        for source in sources:
            session.add(
                AttendanceMergeSourceModel(
                    merge_id=merge_id,
                    source_attendance_id=source.id,
                    source_snapshot=_source_snapshot(source),
                )
            )
        await session.flush()
        result = AttendanceMergeResult(
            merge_id=merge_id,
            canonical_attendance_id=canonical.id,
            employee_id=employee_id,
            work_date=work_date,
            clock_in_at=actual_start,
            clock_out_at=actual_end,
            schedule_code=template.schedule_code,
        )
        affected_user_id = sources[0].user_id

    queue_recent_attendance_refresh(affected_user_id)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{canonical_attendance_id}/audit",
    response_model=ResponseEnvelope[AttendanceMergeAudit],
)
async def get_attendance_merge_audit(
    canonical_attendance_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    _require_hr_admin(claims)
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        merge = await session.scalar(
            select(AttendanceMergeModel).where(
                AttendanceMergeModel.canonical_attendance_id == canonical_attendance_id,
            )
        )
        if merge is None:
            raise HTTPException(status_code=404, detail="Attendance merge audit was not found.")
        template = await session.get(ScheduleTemplateModel, merge.schedule_template_id)
        if template is None:
            raise RuntimeError("Attendance merge audit references a missing schedule template.")
        sources = list(
            (
                await session.scalars(
                    select(AttendanceMergeSourceModel)
                    .where(AttendanceMergeSourceModel.merge_id == merge.id)
                    .order_by(AttendanceMergeSourceModel.source_attendance_id)
                )
            ).all()
        )
        data = AttendanceMergeAudit(
            merge_id=merge.id,
            canonical_attendance_id=canonical_attendance_id,
            employee_id=merge.employee_id,
            work_date=merge.work_date,
            schedule_template_id=merge.schedule_template_id,
            schedule_code=template.schedule_code,
            merged_by=merge.merged_by,
            merged_at=merge.merged_at,
            reason=merge.reason,
            canonical_clock_in_at=merge.canonical_clock_in_at,
            canonical_clock_out_at=merge.canonical_clock_out_at,
            calculation_snapshot=merge.calculation_snapshot,
            sources=[
                AttendanceMergeSourceAudit(
                    source_attendance_id=source.source_attendance_id,
                    source_snapshot=source.source_snapshot,
                )
                for source in sources
            ],
        )
        return ResponseEnvelope(status="success", data=data)
