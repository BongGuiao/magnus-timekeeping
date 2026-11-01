from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.attendance.application.correction_calculation import recalculate_corrected_attendance
from app.attendance.domain.entities.overtime import OvertimeAttendance
from app.attendance.infrastructure.correction_db_model import AttendanceCorrectionModel
from app.attendance.infrastructure.db_model import AttendanceModel, OvertimeApplicationModel
from app.attendance.infrastructure.entity_mapping import copy_fields
from app.attendance.infrastructure.overtime_adapters import queue_recent_attendance_refresh
from app.auth.infrastructure.db_model import UserModel
from app.auth.infrastructure.dependencies import require_permission
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.payroll_cutoffs.application.deadline_policy import CutoffDeadlineError, DeadlineStage, require_attendance_open
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import EmployeeCutoffResultModel
from app.filemaintenance.schedule.infrastructure.db_model import EmployeeScheduleAssignmentModel

router = APIRouter(prefix="/corrections", tags=["Attendance Corrections"])
MANILA = ZoneInfo("Asia/Manila")


@dataclass(frozen=True)
class CorrectionAccount:
    id: UUID
    employee_id: UUID


def _session(uow: GenUnitOfWork) -> AsyncSession:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    return uow.session


class CorrectionCreate(BaseModel):
    work_date: date
    requested_clock_in_at: datetime
    requested_clock_out_at: datetime
    reason: str = Field(min_length=1, max_length=2000)
    supporting_reference: str | None = Field(default=None, max_length=500)
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def validate_period(self) -> "CorrectionCreate":
        for value in (self.requested_clock_in_at, self.requested_clock_out_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Correction times must include a timezone.")
        if self.requested_clock_out_at <= self.requested_clock_in_at:
            raise ValueError("Clock-out must be after clock-in.")
        if self.requested_clock_out_at - self.requested_clock_in_at > timedelta(days=1):
            raise ValueError("A correction cannot span more than 24 hours.")
        if self.requested_clock_in_at.astimezone(MANILA).date() != self.work_date:
            raise ValueError("Clock-in must fall on the selected work date in Philippine time.")
        return self


class CorrectionDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    row_version: int = Field(ge=1)
    review_notes: str = Field(min_length=1, max_length=2000)
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CorrectionOutput(BaseModel):
    id: UUID
    employee_id: UUID
    employee_code: str
    employee_name: str
    work_date: date
    original_clock_in_at: datetime | None
    original_clock_out_at: datetime | None
    requested_clock_in_at: datetime
    requested_clock_out_at: datetime
    reason: str
    supporting_reference: str | None
    status: str
    created_at: datetime
    reviewed_at: datetime | None
    review_notes: str | None
    row_version: int


class CorrectionDay(BaseModel):
    work_date: date
    clock_in_at: datetime | None
    clock_out_at: datetime | None
    expected_clock_in_at: datetime
    expected_clock_out_at: datetime


def _actor_id(claims: dict) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=401, detail="Invalid user id in authentication token.") from error


async def _account(session: AsyncSession, actor_id: UUID, *, lock: bool = False) -> CorrectionAccount:
    statement = select(UserModel).where(UserModel.id == actor_id)
    if lock:
        statement = statement.with_for_update()
    account = await session.scalar(statement)
    if account is None or account.employee_id is None:
        raise HTTPException(status_code=403, detail="An employee-linked account is required.")
    return CorrectionAccount(account.id, account.employee_id)


def _active_assignment(as_of: date):
    return (
        EmploymentAssignmentModel.is_active.is_(True), EmploymentAssignmentModel.status == "ACTIVE",
        EmploymentAssignmentModel.effective_from <= as_of,
        or_(EmploymentAssignmentModel.effective_to.is_(None), EmploymentAssignmentModel.effective_to >= as_of),
        or_(EmploymentAssignmentModel.separation_date.is_(None), EmploymentAssignmentModel.separation_date >= as_of),
    )


def _team(supervisor_id: UUID, employee_column):
    return exists(select(EmploymentAssignmentModel.id).where(
        EmploymentAssignmentModel.employee_id == employee_column,
        EmploymentAssignmentModel.supervisor_employee_id == supervisor_id,
        *_active_assignment(datetime.now(timezone.utc).astimezone(MANILA).date()),
    ))


async def _attendance(session: AsyncSession, user_id: UUID, work_date: date) -> AttendanceModel | None:
    records = (await session.scalars(select(AttendanceModel).where(
        AttendanceModel.user_id == user_id, AttendanceModel.work_date == work_date,
    ).with_for_update())).all()
    if len(records) > 1:
        raise HTTPException(status_code=409, detail="Duplicate attendance records exist for this date; contact HR.")
    return records[0] if records else None


async def _day(session: AsyncSession, account: CorrectionAccount, work_date: date, record: AttendanceModel | None) -> OvertimeAttendance:
    if record is None:
        raise HTTPException(status_code=409, detail="At least one existing clock-in or clock-out is required for this work date; contact HR.")
    if await session.scalar(select(EmployeeScheduleAssignmentModel.id).where(
        EmployeeScheduleAssignmentModel.employee_id == account.employee_id,
        EmployeeScheduleAssignmentModel.status == "APPROVED", EmployeeScheduleAssignmentModel.is_active.is_(True),
        EmployeeScheduleAssignmentModel.attendance_mode == "SCHEDULE_CREDITED",
        EmployeeScheduleAssignmentModel.effective_from <= work_date,
        or_(EmployeeScheduleAssignmentModel.effective_to.is_(None), EmployeeScheduleAssignmentModel.effective_to >= work_date),
    ).limit(1)):
        raise HTTPException(status_code=409, detail="Schedule-credited attendance does not require missing-punch corrections.")
    if record.is_locked or record.record_status != "VALID":
        raise HTTPException(status_code=409, detail="Locked or invalid attendance must be resolved by HR before punch correction.")
    day = copy_fields(record, OvertimeAttendance)
    _require_existing_punch(day)
    if day.expected_clock_in_at is None or day.expected_clock_out_at is None:
        raise HTTPException(status_code=409, detail="A scheduled working day is required for a missing-punch correction.")
    if datetime.now(timezone.utc) <= day.expected_clock_out_at:
        raise HTTPException(status_code=409, detail="File a missing-punch correction only after the scheduled shift has ended.")
    return day


def _require_existing_punch(day: OvertimeAttendance) -> None:
    if day.effective_clock_in is None and day.effective_clock_out is None:
        raise HTTPException(status_code=409, detail="At least one existing clock-in or clock-out is required for this work date; contact HR.")


def _validate_missing(day: OvertimeAttendance, payload: CorrectionCreate) -> None:
    _require_existing_punch(day)
    if day.effective_clock_in is not None and day.effective_clock_out is not None:
        raise HTTPException(status_code=409, detail="Both punches already exist; this workflow only fills missing punches.")
    for original, requested in (
        (day.effective_clock_in, payload.requested_clock_in_at),
        (day.effective_clock_out, payload.requested_clock_out_at),
    ):
        if original is not None and original != requested:
            raise HTTPException(status_code=409, detail="Existing punches cannot be changed by a missing-punch request.")
    if payload.requested_clock_out_at > datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Correction times cannot be in the future.")
    for name in ("first_break_out_at", "first_break_in_at", "meal_break_out_at", "meal_break_in_at",
                 "second_break_out_at", "second_break_in_at", "ot_break_out_at", "ot_break_in_at"):
        value = getattr(day, name)
        if value is not None and not payload.requested_clock_in_at <= value <= payload.requested_clock_out_at:
            raise HTTPException(status_code=409, detail="The requested times must contain all recorded break punches.")


def _output(request: AttendanceCorrectionModel, employee: EmployeeModel | None) -> CorrectionOutput:
    if employee is None:
        raise HTTPException(status_code=409, detail="The employee profile is missing; contact HR.")
    return CorrectionOutput(
        **{name: getattr(request, name) for name in CorrectionOutput.model_fields
           if name not in {"employee_code", "employee_name"}},
        employee_code=employee.employee_no,
        employee_name=" ".join(filter(None, (employee.first_name, employee.last_name))),
    )


async def _open(session: AsyncSession, employee_id: UUID, work_date: date, stage: DeadlineStage) -> list[PayrollCutoffModel]:
    try:
        return await require_attendance_open(
            session, employee_id, work_date, work_date, stage=stage, lock_for_update=True,
        )
    except CutoffDeadlineError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/day", response_model=ResponseEnvelope[CorrectionDay])
async def correction_day(
    work_date: date = Query(), claims: dict = Depends(require_permission("attendance.correct_own")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    async with uow as active:
        session = _session(active)
        account = await _account(session, _actor_id(claims))
        await _open(session, account.employee_id, work_date, "FILING")
        day = await _day(session, account, work_date, await _attendance(session, account.id, work_date))
        result = CorrectionDay(
            work_date=work_date, clock_in_at=day.effective_clock_in, clock_out_at=day.effective_clock_out,
            expected_clock_in_at=day.expected_clock_in_at, expected_clock_out_at=day.expected_clock_out_at,
        )
    return ResponseEnvelope(status="success", data=result)


@router.get("", response_model=ResponseEnvelope[list[CorrectionOutput]])
async def list_corrections(
    claims: dict = Depends(require_permission("attendance.correct_own")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    async with uow as active:
        session = _session(active)
        account = await _account(session, _actor_id(claims))
        rows = (await session.execute(
            select(AttendanceCorrectionModel, EmployeeModel)
            .join(EmployeeModel, EmployeeModel.id == AttendanceCorrectionModel.employee_id)
            .where(AttendanceCorrectionModel.user_id == account.id)
            .order_by(AttendanceCorrectionModel.created_at.desc()).limit(100)
        )).all()
        result = [_output(request, employee) for request, employee in rows]
    return ResponseEnvelope(status="success", data=result)


@router.get("/pending", response_model=ResponseEnvelope[list[CorrectionOutput]])
async def pending_corrections(
    claims: dict = Depends(require_permission("attendance.approve_corrections_team")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    async with uow as active:
        session = _session(active)
        account = await _account(session, _actor_id(claims))
        rows = (await session.execute(
            select(AttendanceCorrectionModel, EmployeeModel)
            .join(EmployeeModel, EmployeeModel.id == AttendanceCorrectionModel.employee_id)
            .where(AttendanceCorrectionModel.status == "PENDING",
                   AttendanceCorrectionModel.employee_id != account.employee_id,
                   _team(account.employee_id, AttendanceCorrectionModel.employee_id))
            .order_by(AttendanceCorrectionModel.created_at).limit(200)
        )).all()
        result = [_output(request, employee) for request, employee in rows]
    return ResponseEnvelope(status="success", data=result)


@router.post("", response_model=ResponseEnvelope[CorrectionOutput], status_code=201)
async def create_correction(
    payload: CorrectionCreate, claims: dict = Depends(require_permission("attendance.correct_own")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor = _actor_id(claims)
    async with uow as active:
        session = _session(active)
        account = await _account(session, actor, lock=True)
        await _open(session, account.employee_id, payload.work_date, "FILING")
        if not await session.scalar(select(EmploymentAssignmentModel.id).where(
            EmploymentAssignmentModel.employee_id == account.employee_id,
            EmploymentAssignmentModel.supervisor_employee_id.is_not(None),
            EmploymentAssignmentModel.supervisor_employee_id != account.employee_id,
            *_active_assignment(datetime.now(timezone.utc).astimezone(MANILA).date()),
        ).limit(1)):
            raise HTTPException(status_code=409, detail="A current supervisor must be assigned before filing a correction.")
        record = await _attendance(session, actor, payload.work_date)
        day = await _day(session, account, payload.work_date, record)
        _validate_missing(day, payload)
        pending = await session.scalar(select(AttendanceCorrectionModel.id).where(
            AttendanceCorrectionModel.employee_id == account.employee_id,
            AttendanceCorrectionModel.work_date == payload.work_date, AttendanceCorrectionModel.status == "PENDING",
        ))
        if pending:
            raise HTTPException(status_code=409, detail="A correction request is already pending for this date.")
        request = AttendanceCorrectionModel(
            **payload.model_dump(), user_id=actor, employee_id=account.employee_id,
            attendance_record_id=record.id if record else None,
            original_clock_in_at=day.effective_clock_in, original_clock_out_at=day.effective_clock_out,
        )
        session.add(request)
        await session.flush()
        await session.refresh(request)
        employee = await session.get(EmployeeModel, account.employee_id)
        result = _output(request, employee)
    await log_entity_action(es_client, user_id=actor, action="SUBMIT", resource="attendance_correction",
                            resource_id=str(result.id), after=result.model_dump(mode="json"))
    return ResponseEnvelope(status="success", data=result)


@router.post("/{request_id}/decision", response_model=ResponseEnvelope[CorrectionOutput])
async def decide_correction(
    request_id: UUID, payload: CorrectionDecision,
    claims: dict = Depends(require_permission("attendance.approve_corrections_team")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor = _actor_id(claims)
    async with uow as active:
        session = _session(active)
        reviewer = await _account(session, actor)
        request = await session.scalar(select(AttendanceCorrectionModel).where(
            AttendanceCorrectionModel.id == request_id,
            AttendanceCorrectionModel.employee_id != reviewer.employee_id,
            _team(reviewer.employee_id, AttendanceCorrectionModel.employee_id),
        ).with_for_update())
        if request is None:
            raise HTTPException(status_code=404, detail="Correction request not found for your direct reports.")
        if request.status != "PENDING" or request.row_version != payload.row_version:
            raise HTTPException(status_code=409, detail="This request has changed or was already reviewed; reload the list.")
        account = await _account(session, request.user_id, lock=True)
        if account.employee_id != request.employee_id:
            raise HTTPException(status_code=409, detail="The request account is no longer linked to this employee; contact HR.")
        cutoffs = await _open(session, request.employee_id, request.work_date, "APPROVAL")
        if payload.decision == "APPROVED":
            record = await _attendance(session, request.user_id, request.work_date)
            if record is None:
                raise HTTPException(status_code=409, detail="The original attendance record is missing; reject this request and contact HR.")
            day = await _day(session, account, request.work_date, record)
            if (day.effective_clock_in, day.effective_clock_out) != (
                request.original_clock_in_at, request.original_clock_out_at,
            ):
                raise HTTPException(status_code=409, detail="Attendance punches changed after filing; reject this request and file a new one.")
            submitted = CorrectionCreate(
                work_date=request.work_date, requested_clock_in_at=request.requested_clock_in_at,
                requested_clock_out_at=request.requested_clock_out_at, reason=request.reason,
            )
            _validate_missing(day, submitted)
            if await session.scalar(select(OvertimeApplicationModel.id).where(
                OvertimeApplicationModel.attendance_record_id == record.id,
                OvertimeApplicationModel.status != "REJECTED",
            ).limit(1)):
                raise HTTPException(status_code=409, detail="Resolve existing overtime applications before correcting these punches.")
            try:
                values = recalculate_corrected_attendance(day, request.requested_clock_in_at, request.requested_clock_out_at)
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            if request.original_clock_in_at is None:
                record.corrected_clock_in_at = request.requested_clock_in_at
            if request.original_clock_out_at is None:
                record.corrected_clock_out_at = request.requested_clock_out_at
            for name, value in values.items():
                setattr(record, name, value)
            record.is_manual_entry = True
            record.correction_reason = request.reason
            record.approved_by_id = actor
            record.approved_at = datetime.now(timezone.utc)
            record.updated_by = actor
            await session.flush()
            request.attendance_record_id = record.id
            for cutoff in cutoffs:
                cutoff.calculation_version = None
                cutoff.updated_by = actor
                cutoff.row_version += 1
                await session.execute(update(EmployeeCutoffResultModel).where(
                    EmployeeCutoffResultModel.cutoff_id == cutoff.id,
                    EmployeeCutoffResultModel.employee_id == request.employee_id,
                ).values(employee_confirmation_status="PENDING", supervisor_status="PENDING", hr_status="PENDING", payroll_status="HOLD"))
        request.status = payload.decision
        request.reviewed_by = actor
        request.reviewed_at = datetime.now(timezone.utc)
        request.review_notes = payload.review_notes
        request.row_version += 1
        await session.flush()
        await session.refresh(request)
        employee = await session.get(EmployeeModel, request.employee_id)
        result = _output(request, employee)
    if payload.decision == "APPROVED":
        queue_recent_attendance_refresh(request.user_id)
    await log_entity_action(es_client, user_id=actor, action=payload.decision, resource="attendance_correction",
                            resource_id=str(result.id), after=result.model_dump(mode="json"))
    return ResponseEnvelope(status="success", data=result)
