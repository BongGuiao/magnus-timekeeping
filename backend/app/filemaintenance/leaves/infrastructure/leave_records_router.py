from datetime import date, datetime, timedelta
from dataclasses import asdict
import logging
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from kombu.exceptions import OperationalError
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.attendance.application.use_case import resolve_attendance_day_type, resolve_schedule_day
from app.attendance.domain.worked_minutes import NONWORKING_DAY_TYPES
from app.auth.infrastructure.dependencies import (
    require_approval_permission, require_permission,
)
from app.auth.infrastructure.hr_dashboard_access import require_hr_dashboard_access
from app.core.audit_logging import stamp_audit_fields
from app.core.config import settings
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.leaves.application.entitlement_upload_use_case import (
    EntitlementUploadChangedError,
    EntitlementUploadInvalidError,
    EntitlementUploadUseCase,
)
from app.filemaintenance.leaves.application.leave_duration import calculate_leave_duration
from app.filemaintenance.leaves.application.leave_records_use_case import (
    EmployeeEntitlementUseCase,
    LeaveApplicationDateUseCase,
    LeaveApplicationUseCase,
    LeaveLedgerUseCase,
)
from app.filemaintenance.leaves.domain.entities.leave_records import (
    EmployeeEntitlementEntity,
    LeaveApplicationDateEntity,
    LeaveApplicationEntity,
    LeaveLedgerEntity,
)
from app.filemaintenance.leaves.infrastructure.leave_records_dependencies import (
    get_entitlement_upload_use_case,
    get_employee_entitlement_use_case,
    get_leave_application_date_use_case,
    get_leave_application_use_case,
    get_leave_ledger_use_case,
)
from app.filemaintenance.leaves.infrastructure.entitlement_upload_csv import entitlement_upload_csv_template
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel
from app.filemaintenance.holidays.calendar.infrastructure.db_model import HolidayCalendarModel
from app.filemaintenance.holidays.holiday.infrastructure.db_model import HolidayModel
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import LeaveApplicationDateModel, LeaveApplicationModel
from app.tasks.dashboard_tasks import (
    LEAVE_DASHBOARD_SNAPSHOT_PREFIX,
    refresh_leave_dashboard_snapshots,
)

entitlements_router = APIRouter(
    prefix="/employee-entitlements",
    tags=["Employee Leave Entitlements"],
    dependencies=[Depends(require_permission("leave.manage"))],
)
applications_router = APIRouter(prefix="/leave-applications", tags=["Leave Applications"])
ledger_router = APIRouter(
    prefix="/leave-ledger",
    tags=["Leave Ledger"],
    dependencies=[Depends(require_permission("leave.manage"))],
)
logger = logging.getLogger(__name__)
PH_TIMEZONE = ZoneInfo("Asia/Manila")
MAX_ENTITLEMENT_UPLOAD_BYTES = 1024 * 1024
MAX_REST_DAY_CHECK_DAYS = 93


def _actor_id(claims: dict[str, Any]) -> UUID:
    if not claims.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token.",
        )
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error


def _employee_id(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to an employee profile.",
        ) from error


def _require_employee_draft_application(claims: dict[str, Any], application: Any) -> None:
    if claims.get("role") != "admin" and application.status != "DRAFT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only draft leave applications can be changed by an employee.",
        )


def _require_record(record: Any, message: str):
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    return record


def _validate_nullable_patch(model: BaseModel, nullable_fields: set[str]) -> None:
    for field_name in model.model_fields_set - nullable_fields:
        if getattr(model, field_name) is None:
            raise ValueError(f"{field_name} cannot be null.")


def _validate_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset.")


def _queue_leave_dashboard_refresh(employee_id: UUID) -> None:
    try:
        refresh_leave_dashboard_snapshots.delay(str(employee_id))
    except OperationalError:
        logger.exception(
            "Leave data was saved, but its dashboard snapshot refresh could not be queued.",
            extra={"employee_id": str(employee_id)},
        )


class ApprovedLeaveForReversal(BaseModel):
    id: UUID
    application_no: str
    employee_no: str
    employee_name: str
    leave_type: str
    start_at: datetime
    end_at: datetime
    paid_minutes: int


class ApprovedLeaveReversalPage(BaseModel):
    items: list[ApprovedLeaveForReversal]
    next_offset: int | None


class LeaveReversalRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


@applications_router.get("/hr/approved", response_model=ResponseEnvelope[ApprovedLeaveReversalPage])
async def list_approved_leave_for_reversal(
    from_date: date, to_date: date,
    offset: int = Query(default=0, ge=0),
    actor: tuple[UUID, UUID] = Depends(require_hr_dashboard_access),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    sort_by: Literal["application", "employee", "leave", "coverage", "paid_minutes"] = "coverage",
    sort_direction: Literal["asc", "desc"] = "desc",
):
    if to_date < from_date or (to_date - from_date).days > 365:
        raise HTTPException(status_code=422, detail="Choose a date range of at most 366 days.")
    start = datetime.combine(from_date, datetime.min.time(), tzinfo=PH_TIMEZONE)
    end = datetime.combine(to_date + timedelta(days=1), datetime.min.time(), tzinfo=PH_TIMEZONE)
    sort_columns = {
        "application": (func.lower(LeaveApplicationModel.application_no),),
        "employee": (func.lower(EmployeeModel.first_name), func.lower(EmployeeModel.last_name)),
        "leave": (func.lower(LeaveTypeModel.leave_name),),
        "coverage": (LeaveApplicationModel.start_at,),
        "paid_minutes": (func.coalesce(LeaveApplicationModel.paid_minutes, 0),),
    }[sort_by]
    ordering = [column.asc() if sort_direction == "asc" else column.desc() for column in sort_columns]
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        rows = (await session.execute(
            select(LeaveApplicationModel, EmployeeModel, LeaveTypeModel)
            .join(EmployeeModel, EmployeeModel.id == LeaveApplicationModel.employee_id)
            .join(LeaveTypeModel, LeaveTypeModel.id == LeaveApplicationModel.leave_type_id)
            .where(
                LeaveApplicationModel.status == "APPROVED",
                LeaveApplicationModel.is_active.is_(True),
                LeaveApplicationModel.employee_id != actor[1],
                LeaveApplicationModel.start_at < end, LeaveApplicationModel.end_at > start,
            )
            .order_by(*ordering, LeaveApplicationModel.id)
            .offset(offset).limit(26)
        )).all()
    items = [
        ApprovedLeaveForReversal(
            id=application.id, application_no=application.application_no,
            employee_no=employee.employee_no, employee_name=f"{employee.first_name} {employee.last_name}",
            leave_type=leave_type.leave_name, start_at=application.start_at, end_at=application.end_at,
            paid_minutes=application.paid_minutes or 0,
        )
        for application, employee, leave_type in rows[:25]
    ]
    return ResponseEnvelope(status="success", data=ApprovedLeaveReversalPage(
        items=items, next_offset=offset + 25 if len(rows) > 25 else None,
    ))


@applications_router.post("/{application_id}/return-for-approval", response_model=ResponseEnvelope[LeaveApplicationEntity])
async def return_approved_leave_for_approval(
    application_id: UUID, payload: LeaveReversalRequest,
    actor: tuple[UUID, UUID] = Depends(require_hr_dashboard_access),
    use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    before = _require_record(await use_case.get(application_id), "Leave application not found.")
    try:
        result = await use_case.return_approved_to_pending(application_id, actor[0], actor[1], payload.reason)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    result = _require_record(result, "Leave application not found.")
    await log_entity_action(
        es_client, user_id=actor[0], action="RETURN_FOR_APPROVAL", resource="leave_application",
        resource_id=application_id, before=before, after=result,
    )
    _queue_leave_dashboard_refresh(result.employee_id)
    return ResponseEnvelope(status="success", data=result)


class LeaveRestDayCheck(BaseModel):
    rest_days: list[date]
    unchecked_dates: list[date]


class LeaveDurationPreview(BaseModel):
    requested_minutes: int
    holidays: list[date]
    rest_days: list[date]


class HolidayLeaveReviewItem(BaseModel):
    application_no: str
    employee_no: str
    employee_name: str
    leave_type: str
    start_at: datetime
    end_at: datetime
    requested_minutes: int
    paid_minutes: int
    holiday_dates: list[date]
    has_daily_breakdown: bool


class HolidayLeaveReview(BaseModel):
    items: list[HolidayLeaveReviewItem]
    next_offset: int | None


@entitlements_router.get("/holiday-review", response_model=ResponseEnvelope[HolidayLeaveReview])
async def review_holiday_leave(
    from_date: date,
    to_date: date,
    offset: int = Query(default=0, ge=0),
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    _actor_id(claims)
    if to_date < from_date or (to_date - from_date).days > 365:
        raise HTTPException(status_code=422, detail="Choose a date range of at most 366 days.")
    start = datetime.combine(from_date, datetime.min.time(), tzinfo=PH_TIMEZONE)
    end = datetime.combine(to_date + timedelta(days=1), datetime.min.time(), tzinfo=PH_TIMEZONE)
    page_size = 25
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        applications = (await session.execute(
            select(LeaveApplicationModel, EmployeeModel, LeaveTypeModel)
            .join(EmployeeModel, EmployeeModel.id == LeaveApplicationModel.employee_id)
            .join(LeaveTypeModel, LeaveTypeModel.id == LeaveApplicationModel.leave_type_id)
            .where(
                LeaveApplicationModel.is_active.is_(True),
                LeaveApplicationModel.status == "APPROVED",
                LeaveApplicationModel.paid_minutes > 0,
                LeaveApplicationModel.start_at < end,
                LeaveApplicationModel.end_at > start,
            )
            .order_by(LeaveApplicationModel.start_at, LeaveApplicationModel.id)
            .offset(offset).limit(page_size + 1)
        )).all()
        has_next = len(applications) > page_size
        applications = applications[:page_size]
        holiday_dates = set((await session.scalars(
            select(HolidayModel.holiday_date).join(
                HolidayCalendarModel, HolidayCalendarModel.id == HolidayModel.holiday_calendar_id,
            ).where(
                HolidayModel.holiday_date.between(from_date, to_date),
                HolidayModel.status == "ACTIVE", HolidayModel.is_active.is_(True),
                HolidayCalendarModel.status == "PUBLISHED", HolidayCalendarModel.is_active.is_(True),
            )
        )).all())
        ids = [application.id for application, _, _ in applications]
        dates_by_application: dict[UUID, list[LeaveApplicationDateModel]] = {}
        if ids:
            for day in (await session.scalars(
                select(LeaveApplicationDateModel).where(LeaveApplicationDateModel.leave_application_id.in_(ids))
            )).all():
                dates_by_application.setdefault(day.leave_application_id, []).append(day)
        items = []
        resolved: dict[tuple[UUID, date], str] = {}
        for application, employee, leave_type in applications:
            first = max(from_date, application.start_at.astimezone(PH_TIMEZONE).date())
            last = min(to_date, (application.end_at - timedelta(microseconds=1)).astimezone(PH_TIMEZONE).date())
            rows = dates_by_application.get(application.id, [])
            reliable_days = bool(rows) and sum(row.approved_paid_minutes for row in rows) == application.paid_minutes
            paid_days = {row.leave_date for row in rows if row.approved_paid_minutes > 0}
            potential = []
            for day in sorted(holiday_dates):
                if day < first or day > last or (reliable_days and day not in paid_days):
                    continue
                key = (application.employee_id, day)
                if key not in resolved:
                    resolved[key] = await resolve_attendance_day_type(session, *key)
                if resolved[key] in NONWORKING_DAY_TYPES:
                    potential.append(day)
            if potential:
                items.append(HolidayLeaveReviewItem(
                    application_no=application.application_no,
                    employee_no=employee.employee_no,
                    employee_name=f"{employee.first_name} {employee.last_name}",
                    leave_type=leave_type.leave_name,
                    start_at=application.start_at,
                    end_at=application.end_at,
                    requested_minutes=application.requested_minutes,
                    paid_minutes=application.paid_minutes,
                    holiday_dates=potential,
                    has_daily_breakdown=reliable_days,
                ))
    return ResponseEnvelope(status="success", data=HolidayLeaveReview(
        items=items, next_offset=offset + page_size if has_next else None,
    ))


@applications_router.get("/duration-preview", response_model=ResponseEnvelope[LeaveDurationPreview])
async def preview_leave_duration(
    start_at: AwareDatetime,
    end_at: AwareDatetime,
    claims: dict[str, Any] = Depends(require_approval_permission("leave.submit")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    _actor_id(claims)
    employee_id = _employee_id(claims)
    async with uow as active_uow:
        if active_uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        try:
            duration = await calculate_leave_duration(active_uow.session, employee_id, start_at, end_at)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    return ResponseEnvelope(
        status="success",
        data=LeaveDurationPreview(
            requested_minutes=duration.requested_minutes,
            holidays=list(duration.holidays),
            rest_days=list(duration.rest_days),
        ),
    )


@applications_router.get("/rest-day-check", response_model=ResponseEnvelope[LeaveRestDayCheck])
async def check_leave_rest_days(
    start_at: AwareDatetime,
    end_at: AwareDatetime,
    claims: dict[str, Any] = Depends(require_approval_permission("leave.submit")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    _actor_id(claims)
    employee_id = _employee_id(claims)
    if end_at <= start_at:
        raise HTTPException(status_code=422, detail="end_at must be later than start_at.")
    first = start_at.astimezone(PH_TIMEZONE).date()
    last = (end_at - timedelta(microseconds=1)).astimezone(PH_TIMEZONE).date()
    count = (last - first).days + 1
    if count > MAX_REST_DAY_CHECK_DAYS:
        raise HTTPException(status_code=422, detail=f"Rest-day checks are limited to {MAX_REST_DAY_CHECK_DAYS} days.")

    rest_days = []
    unchecked_dates = []
    async with uow as active_uow:
        if active_uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        for offset in range(count):
            work_date = first + timedelta(days=offset)
            schedule = await resolve_schedule_day(active_uow.session, employee_id, work_date)
            context = schedule.schedule_context or {}
            if not (context.get("schedule_assignment_id") or context.get("emergency_schedule_request_id")):
                unchecked_dates.append(work_date)
            elif schedule.work_type == "REST":
                rest_days.append(work_date)
    return ResponseEnvelope(status="success", data=LeaveRestDayCheck(rest_days=rest_days, unchecked_dates=unchecked_dates))


class EntitlementCreateSchema(BaseModel):
    employee_id: UUID
    leave_type_id: UUID
    entitlement_year: int = Field(ge=1900, le=2200)
    opening_minutes: int = 0
    granted_minutes: int = 0
    accrued_minutes: int = 0
    carryover_minutes: int = 0
    adjustment_minutes: int = 0
    used_minutes: int = Field(default=0, ge=0)
    reserved_minutes: int = Field(default=0, ge=0)
    expired_minutes: int = Field(default=0, ge=0)
    converted_minutes: int = Field(default=0, ge=0)
    available_minutes: int = 0
    last_calculated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_last_calculated_at(self):
        if self.last_calculated_at is not None:
            _validate_aware_datetime(self.last_calculated_at, "last_calculated_at")
        return self


class EntitlementUpdateSchema(BaseModel):
    employee_id: UUID | None = None
    leave_type_id: UUID | None = None
    entitlement_year: int | None = Field(default=None, ge=1900, le=2200)
    opening_minutes: int | None = None
    granted_minutes: int | None = None
    accrued_minutes: int | None = None
    carryover_minutes: int | None = None
    adjustment_minutes: int | None = None
    used_minutes: int | None = Field(default=None, ge=0)
    reserved_minutes: int | None = Field(default=None, ge=0)
    expired_minutes: int | None = Field(default=None, ge=0)
    converted_minutes: int | None = Field(default=None, ge=0)
    available_minutes: int | None = None
    last_calculated_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_patch(self):
        _validate_nullable_patch(self, {"last_calculated_at"})
        if self.last_calculated_at is not None:
            _validate_aware_datetime(self.last_calculated_at, "last_calculated_at")
        return self


class EntitlementUploadPreviewRowSchema(BaseModel):
    row_no: int
    employee_no: str
    leave_code: str
    entitlement_year: int | None
    employee_name: str | None
    leave_name: str | None
    unit_type: str | None
    action: Literal["CREATE", "UPDATE"] | None
    errors: list[str]
    before: dict[str, int] | None
    after: dict[str, int] | None


class EntitlementUploadPreviewSchema(BaseModel):
    is_valid: bool
    error_count: int
    file_errors: list[str]
    rows: list[EntitlementUploadPreviewRowSchema]
    preview_token: str | None


class EntitlementUploadResultSchema(BaseModel):
    created: int
    updated: int
    employee_ids: list[UUID]
    entitlement_ids: list[UUID]


class LeaveApplicationCreateSchema(BaseModel):
    application_no: str = Field(min_length=1, max_length=50)
    employee_id: UUID | None = None
    leave_type_id: UUID
    start_at: datetime
    end_at: datetime
    duration_type: str = Field(min_length=1, max_length=20)
    requested_minutes: int = Field(ge=0)
    paid_minutes: int | None = Field(default=None, ge=0)
    unpaid_minutes: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1)
    contact_information: str | None = None
    reliever_employee_id: UUID | None = None
    is_retroactive: bool = False
    workflow_instance_id: UUID | None = None
    status: str = Field(default="DRAFT", min_length=1, max_length=30)
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    cancelled_at: datetime | None = None
    payroll_posted: bool = False
    is_active: bool = True

    @model_validator(mode="after")
    def validate_times(self):
        for field_name in ("start_at", "end_at", "submitted_at", "approved_at", "cancelled_at"):
            value = getattr(self, field_name)
            if value is not None:
                _validate_aware_datetime(value, field_name)
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at.")
        return self


class LeaveApplicationUpdateSchema(BaseModel):
    id: UUID
    application_no: str | None = Field(default=None, min_length=1, max_length=50)
    employee_id: UUID | None = None
    leave_type_id: UUID | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    duration_type: str | None = Field(default=None, min_length=1, max_length=20)
    requested_minutes: int | None = Field(default=None, ge=0)
    paid_minutes: int | None = Field(default=None, ge=0)
    unpaid_minutes: int | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, min_length=1)
    contact_information: str | None = None
    reliever_employee_id: UUID | None = None
    is_retroactive: bool | None = None
    workflow_instance_id: UUID | None = None
    status: str | None = Field(default=None, min_length=1, max_length=30)
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    cancelled_at: datetime | None = None
    payroll_posted: bool | None = None
    is_active: bool | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_patch(self):
        _validate_nullable_patch(
            self,
            {
                "paid_minutes",
                "unpaid_minutes",
                "contact_information",
                "reliever_employee_id",
                "workflow_instance_id",
                "submitted_at",
                "approved_at",
                "cancelled_at",
            },
        )
        for field_name in ("start_at", "end_at", "submitted_at", "approved_at", "cancelled_at"):
            value = getattr(self, field_name)
            if value is not None:
                _validate_aware_datetime(value, field_name)
        return self


class LeaveDashboardBalanceSchema(BaseModel):
    type: str
    label: str
    unit_type: str
    allotted_minutes: int
    used_minutes: int
    available_minutes: int
    pending_minutes: int = 0
    entitlement_year: int


class LeaveDashboardApplicationSchema(BaseModel):
    id: UUID
    application_no: str
    type: str
    leave_type_id: UUID
    unit_type: str
    requested_minutes: int
    start_at: datetime
    end_at: datetime
    status: str


class LeaveDashboardSnapshotSchema(BaseModel):
    balances: list[LeaveDashboardBalanceSchema]
    applications: list[LeaveDashboardApplicationSchema]
    refreshed_at: datetime


class SupervisorPendingLeaveSchema(BaseModel):
    id: UUID
    application_no: str
    employee_id: UUID
    employee_no: str
    employee_name: str
    leave_type_id: UUID
    leave_type_name: str
    unit_type: str
    start_at: datetime
    end_at: datetime
    requested_minutes: int
    reason: str
    created_at: datetime | None
    status: str


class SupervisorLeaveDecisionSchema(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]


class LeaveApplicationDateCreateSchema(BaseModel):
    leave_date: date
    roster_id: UUID | None = None
    requested_minutes: int = Field(ge=0)
    approved_paid_minutes: int = Field(default=0, ge=0)
    approved_unpaid_minutes: int = Field(default=0, ge=0)
    holiday_flag: bool = False
    rest_day_flag: bool = False
    attendance_overlap_minutes: int = Field(default=0, ge=0)
    final_charge_minutes: int = Field(default=0, ge=0)


class LeaveApplicationDateUpdateSchema(BaseModel):
    id: UUID
    leave_date: date | None = None
    roster_id: UUID | None = None
    requested_minutes: int | None = Field(default=None, ge=0)
    approved_paid_minutes: int | None = Field(default=None, ge=0)
    approved_unpaid_minutes: int | None = Field(default=None, ge=0)
    holiday_flag: bool | None = None
    rest_day_flag: bool | None = None
    attendance_overlap_minutes: int | None = Field(default=None, ge=0)
    final_charge_minutes: int | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_patch(self):
        _validate_nullable_patch(self, {"roster_id"})
        return self


class LeaveLedgerCreateSchema(BaseModel):
    employee_id: UUID
    leave_type_id: UUID
    transaction_date: date
    transaction_type: str = Field(min_length=1, max_length=30)
    reference_type: str = Field(min_length=1, max_length=30)
    reference_id: UUID | None = None
    minutes_delta: int
    balance_after_minutes: int
    remarks: str | None = None


async def _read_entitlement_upload(file: UploadFile) -> bytes:
    if not (file.filename or "").strip().lower().endswith(".csv"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a .csv file.")
    content = await file.read(MAX_ENTITLEMENT_UPLOAD_BYTES + 1)
    if len(content) > MAX_ENTITLEMENT_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The file is larger than 1 MB. Split it into smaller uploads.",
        )
    return content


@entitlements_router.get("/upload/template")
async def download_entitlement_upload_template(
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
):
    _actor_id(claims)
    return Response(
        content=entitlement_upload_csv_template(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="entitlement_upload_template.csv"'},
    )


@entitlements_router.post(
    "/upload/preview",
    response_model=ResponseEnvelope[EntitlementUploadPreviewSchema],
)
async def preview_entitlement_upload(
    file: UploadFile = File(...),
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
    use_case: EntitlementUploadUseCase = Depends(get_entitlement_upload_use_case),
):
    _actor_id(claims)
    preview = await use_case.preview(await _read_entitlement_upload(file))
    return ResponseEnvelope(status="success", data=EntitlementUploadPreviewSchema(**asdict(preview)))


@entitlements_router.post(
    "/upload",
    response_model=ResponseEnvelope[EntitlementUploadResultSchema],
)
async def apply_entitlement_upload(
    file: UploadFile = File(...),
    preview_token: str = Form(..., min_length=64, max_length=64, pattern="^[0-9a-f]{64}$"),
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
    use_case: EntitlementUploadUseCase = Depends(get_entitlement_upload_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    content = await _read_entitlement_upload(file)
    try:
        result = await use_case.apply(content, preview_token)
    except EntitlementUploadInvalidError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    except EntitlementUploadChangedError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    entitlement_ids: list[UUID] = []
    for change in result.changes:
        entitlement_id = change.after.id
        if entitlement_id is None:
            raise RuntimeError("An uploaded entitlement did not receive an ID.")
        entitlement_ids.append(entitlement_id)
        await log_entity_action(
            es_client,
            user_id=actor_id,
            action=change.action,
            resource="employee_entitlement",
            resource_id=entitlement_id,
            before=change.before,
            after=change.after,
        )
    employee_ids = sorted({change.after.employee_id for change in result.changes}, key=str)
    for employee_id in employee_ids:
        _queue_leave_dashboard_refresh(employee_id)
    return ResponseEnvelope(
        status="success",
        data=EntitlementUploadResultSchema(
            created=sum(change.action == "CREATE" for change in result.changes),
            updated=sum(change.action == "UPDATE" for change in result.changes),
            employee_ids=employee_ids,
            entitlement_ids=entitlement_ids,
        ),
    )


@entitlements_router.post(
    "/create",
    response_model=ResponseEnvelope[EmployeeEntitlementEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_employee_entitlement(
    payload: EntitlementCreateSchema,
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
    use_case: EmployeeEntitlementUseCase = Depends(get_employee_entitlement_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        result = await use_case.create(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    await log_entity_action(
        es_client, user_id=actor_id, action="CREATE", resource="employee_entitlement",
        resource_id=result.id, after=result,
    )
    _queue_leave_dashboard_refresh(result.employee_id)
    return ResponseEnvelope(status="success", data=result)


@entitlements_router.put(
    "/update",
    response_model=ResponseEnvelope[EmployeeEntitlementEntity],
)
async def update_employee_entitlement(
    payload: EntitlementUpdateSchema,
    entitlement_id: UUID,
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
    use_case: EmployeeEntitlementUseCase = Depends(get_employee_entitlement_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    before = _require_record(await use_case.get(entitlement_id), "Employee entitlement not found.")
    values = payload.model_dump(exclude_unset=True)
    try:
        result = _require_record(
            await use_case.update(entitlement_id, values),
            "Employee entitlement not found.",
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    await log_entity_action(
        es_client, user_id=actor_id, action="UPDATE", resource="employee_entitlement",
        resource_id=entitlement_id, before=before, after=result,
    )
    _queue_leave_dashboard_refresh(result.employee_id)
    return ResponseEnvelope(status="success", data=result)


@entitlements_router.get("/list", response_model=ResponseEnvelope[list[EmployeeEntitlementEntity]])
async def list_employee_entitlements(
    employee_id: UUID | None = None,
    leave_type_id: UUID | None = None,
    entitlement_year: int | None = Query(default=None, ge=1900, le=2200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
    use_case: EmployeeEntitlementUseCase = Depends(get_employee_entitlement_use_case),
):
    _actor_id(claims)
    result = await use_case.list(employee_id, leave_type_id, entitlement_year, offset, limit)
    return ResponseEnvelope(status="success", data=result)


@entitlements_router.delete("/{entitlement_id}", response_model=ResponseEnvelope[EmployeeEntitlementEntity])
async def delete_employee_entitlement(
    entitlement_id: UUID,
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
    use_case: EmployeeEntitlementUseCase = Depends(get_employee_entitlement_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    try:
        deleted = _require_record(await use_case.delete(entitlement_id), "Employee entitlement not found.")
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    await log_entity_action(
        es_client, user_id=actor_id, action="DELETE", resource="employee_entitlement",
        resource_id=entitlement_id, before=deleted,
    )
    _queue_leave_dashboard_refresh(deleted.employee_id)
    return ResponseEnvelope(status="success", data=deleted)


@entitlements_router.get("/{entitlement_id}", response_model=ResponseEnvelope[EmployeeEntitlementEntity])
async def get_employee_entitlement(
    entitlement_id: UUID,
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
    use_case: EmployeeEntitlementUseCase = Depends(get_employee_entitlement_use_case),
):
    _actor_id(claims)
    result = _require_record(await use_case.get(entitlement_id), "Employee entitlement not found.")
    return ResponseEnvelope(status="success", data=result)


@applications_router.post(
    "/create",
    response_model=ResponseEnvelope[LeaveApplicationEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_leave_application(
    payload: LeaveApplicationCreateSchema,
    claims: dict[str, Any] = Depends(require_approval_permission("leave.submit")),
    use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    if (
        claims.get("role") != "admin"
        and payload.employee_id is not None
        and payload.employee_id != _employee_id(claims)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only submit a leave application for your own employee account.",
        )
    if claims.get("role") != "admin" and (
        payload.status != "DRAFT"
        or payload.workflow_instance_id is not None
        or payload.submitted_at is not None
        or payload.approved_at is not None
        or payload.cancelled_at is not None
        or payload.payroll_posted
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employees can only create draft leave applications.",
        )
    employee_id = _employee_id(claims) if claims.get("role") != "admin" else payload.employee_id
    if employee_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="employee_id is required when an administrator creates a leave application.",
        )
    if claims.get("role") != "admin" and payload.employee_id not in (None, employee_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only submit a leave application for your own employee account.",
        )
    values = stamp_audit_fields(payload.model_dump(exclude={"employee_id"}), actor_id, creating=True)
    values["employee_id"] = employee_id
    try:
        result = await use_case.create(values)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    await log_entity_action(
        es_client, user_id=actor_id, action="CREATE", resource="leave_application",
        resource_id=result.id, after=result,
    )
    _queue_leave_dashboard_refresh(result.employee_id)
    return ResponseEnvelope(status="success", data=result)


@applications_router.put("/update", response_model=ResponseEnvelope[LeaveApplicationEntity])
async def update_leave_application(
    payload: LeaveApplicationUpdateSchema,
    claims: dict[str, Any] = Depends(require_approval_permission("leave.submit")),
    use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    before = _require_record(await use_case.get(payload.id), "Leave application not found.")
    if claims.get("role") != "admin" and before.employee_id != _employee_id(claims):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update your own leave application.")
    if claims.get("role") != "admin":
        _require_employee_draft_application(claims, before)
        protected_fields = {"workflow_instance_id", "submitted_at", "approved_at", "cancelled_at", "payroll_posted"}
        if (
            protected_fields.intersection(payload.model_fields_set)
            or (payload.status is not None and payload.status != "DRAFT")
            or (payload.employee_id is not None and payload.employee_id != before.employee_id)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Employees cannot change leave workflow or ownership fields.",
            )
    merged_start = payload.start_at if payload.start_at is not None else before.start_at
    merged_end = payload.end_at if payload.end_at is not None else before.end_at
    if merged_end <= merged_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_at must be later than start_at.",
        )
    values = payload.model_dump(exclude_unset=True, exclude={"id"})
    stamp_audit_fields(values, actor_id, creating=False)
    try:
        result = _require_record(
            await use_case.update_with_approval_posting(
                payload.id, values, actor_id,
                expected_employee_id=_employee_id(claims) if claims.get("role") != "admin" else None,
            ),
            "Leave application not found.",
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    await log_entity_action(
        es_client, user_id=actor_id, action="UPDATE", resource="leave_application",
        resource_id=payload.id, before=before, after=result,
    )
    _queue_leave_dashboard_refresh(result.employee_id)
    return ResponseEnvelope(status="success", data=result)


@applications_router.post(
    "/{application_id}/submit",
    response_model=ResponseEnvelope[LeaveApplicationEntity],
)
async def submit_leave_application(
    application_id: UUID,
    claims: dict[str, Any] = Depends(require_approval_permission("leave.submit")),
    use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    before = _require_record(await use_case.get(application_id), "Leave application not found.")
    if claims.get("role") != "admin" and before.employee_id != _employee_id(claims):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only submit your own leave application.",
        )
    try:
        result = await use_case.submit_draft_for_approval(
            application_id, actor_id,
            expected_employee_id=_employee_id(claims) if claims.get("role") != "admin" else None,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    result = _require_record(result, "Leave application not found.")
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="leave_application",
        resource_id=application_id,
        before=before,
        after=result,
    )
    _queue_leave_dashboard_refresh(result.employee_id)
    return ResponseEnvelope(status="success", data=result)


@applications_router.get("/list", response_model=ResponseEnvelope[list[LeaveApplicationEntity]])
async def list_leave_applications(
    employee_id: UUID | None = None,
    leave_type_id: UUID | None = None,
    application_status: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    claims: dict[str, Any] = Depends(require_permission("leave.read_own")),
    use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
):
    _actor_id(claims)
    if claims.get("role") == "admin":
        scoped_employee_id = employee_id
    else:
        scoped_employee_id = _employee_id(claims)
    result = await use_case.list(scoped_employee_id, leave_type_id, application_status, offset, limit)
    return ResponseEnvelope(status="success", data=result)


@applications_router.get(
    "/supervisor/pending/count",
    response_model=ResponseEnvelope[int],
)
async def count_supervisor_pending_leave_applications(
    claims: dict[str, Any] = Depends(require_approval_permission("leave.approve_team")),
    use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
):
    _actor_id(claims)
    supervisor_employee_id = _employee_id(claims)
    count = await use_case.count_pending_for_supervisor(
        supervisor_employee_id,
        datetime.now(PH_TIMEZONE).date(),
    )
    return ResponseEnvelope(status="success", data=count)


@applications_router.get(
    "/supervisor/pending",
    response_model=ResponseEnvelope[list[SupervisorPendingLeaveSchema]],
)
async def list_supervisor_pending_leave_applications(
    claims: dict[str, Any] = Depends(require_approval_permission("leave.approve_team")),
    use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
):
    _actor_id(claims)
    supervisor_employee_id = _employee_id(claims)
    result = await use_case.list_pending_for_supervisor(
        supervisor_employee_id,
        datetime.now(PH_TIMEZONE).date(),
    )
    return ResponseEnvelope(status="success", data=result)


@applications_router.post(
    "/supervisor/{application_id}/decision",
    response_model=ResponseEnvelope[LeaveApplicationEntity],
)
async def decide_supervisor_pending_leave_application(
    application_id: UUID,
    payload: SupervisorLeaveDecisionSchema,
    claims: dict[str, Any] = Depends(require_approval_permission("leave.approve_team")),
    use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    supervisor_employee_id = _employee_id(claims)
    try:
        result = await use_case.decide_pending_for_supervisor(
            supervisor_employee_id,
            application_id,
            payload.decision,
            actor_id,
            datetime.now(PH_TIMEZONE).date(),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending leave application was not found for your team or has already been reviewed.",
        )
    if payload.decision == "APPROVED":
        _queue_leave_dashboard_refresh(result.employee_id)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="leave_application",
        resource_id=application_id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@applications_router.get(
    "/dashboard",
    response_model=ResponseEnvelope[LeaveDashboardSnapshotSchema],
)
async def get_leave_dashboard_snapshot(
    claims: dict[str, Any] = Depends(require_permission("leave.read_own")),
):
    _actor_id(claims)
    employee_id = _employee_id(claims)
    cache_url = settings.DASHBOARD_CACHE_REDIS_URL or f"redis://{settings.REDIS_HOST}:6379/1"
    cache = Redis.from_url(cache_url, decode_responses=True)
    try:
        snapshot_data = await cache.get(f"{LEAVE_DASHBOARD_SNAPSHOT_PREFIX}:{employee_id}")
    except RedisError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The leave dashboard snapshot is temporarily unavailable.",
        ) from error
    finally:
        await cache.aclose()

    if snapshot_data is None:
        try:
            refresh_leave_dashboard_snapshots.delay(str(employee_id))
        except OperationalError:
            logger.exception(
                "Leave dashboard snapshot is missing and its refresh could not be queued.",
                extra={"employee_id": str(employee_id)},
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The leave dashboard is being refreshed. Please try again shortly.",
            headers={"Retry-After": "5"},
        )
    try:
        snapshot = LeaveDashboardSnapshotSchema.model_validate_json(snapshot_data)
    except ValidationError as error:
        logger.exception(
            "Leave dashboard snapshot in Redis is invalid.",
            extra={"employee_id": str(employee_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The leave dashboard snapshot is invalid. Please try again after it refreshes.",
        ) from error

    return ResponseEnvelope(status="success", data=snapshot)


@applications_router.post(
    "/{application_id}/dates",
    response_model=ResponseEnvelope[LeaveApplicationDateEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_leave_application_date(
    application_id: UUID,
    payload: LeaveApplicationDateCreateSchema,
    claims: dict[str, Any] = Depends(require_permission("leave.submit")),
    application_use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
    date_use_case: LeaveApplicationDateUseCase = Depends(get_leave_application_date_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    application = _require_record(
        await application_use_case.get(application_id),
        "Leave application not found.",
    )
    if claims.get("role") != "admin" and application.employee_id != _employee_id(claims):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only manage your own leave applications.")
    _require_employee_draft_application(claims, application)
    if claims.get("role") != "admin" and (
        payload.approved_paid_minutes
        or payload.approved_unpaid_minutes
        or payload.holiday_flag
        or payload.rest_day_flag
        or payload.attendance_overlap_minutes
        or payload.final_charge_minutes
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employees cannot set approval, schedule, or attendance-derived leave values.",
        )
    try:
        result = await date_use_case.create({
            **payload.model_dump(),
            "leave_application_id": application_id,
        })
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    await log_entity_action(
        es_client, user_id=actor_id, action="CREATE", resource="leave_application_date",
        resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@applications_router.get(
    "/{application_id}/dates",
    response_model=ResponseEnvelope[list[LeaveApplicationDateEntity]],
)
async def list_leave_application_dates(
    application_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    claims: dict[str, Any] = Depends(require_permission("leave.read_own")),
    application_use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
    date_use_case: LeaveApplicationDateUseCase = Depends(get_leave_application_date_use_case),
):
    _actor_id(claims)
    application = _require_record(
        await application_use_case.get(application_id),
        "Leave application not found.",
    )
    if claims.get("role") != "admin" and application.employee_id != _employee_id(claims):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own leave applications.")
    result = await date_use_case.list(application_id, offset, limit)
    return ResponseEnvelope(status="success", data=result)


@applications_router.put("/dates/update", response_model=ResponseEnvelope[LeaveApplicationDateEntity])
async def update_leave_application_date(
    payload: LeaveApplicationDateUpdateSchema,
    claims: dict[str, Any] = Depends(require_permission("leave.submit")),
    use_case: LeaveApplicationDateUseCase = Depends(get_leave_application_date_use_case),
    application_use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    before = _require_record(await use_case.get(payload.id), "Leave application date not found.")
    parent = _require_record(
        await application_use_case.get(before.leave_application_id),
        "Leave application not found.",
    )
    if claims.get("role") != "admin" and parent.employee_id != _employee_id(claims):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update your own leave applications.")
    _require_employee_draft_application(claims, parent)
    if claims.get("role") != "admin" and {
        "approved_paid_minutes",
        "approved_unpaid_minutes",
        "holiday_flag",
        "rest_day_flag",
        "attendance_overlap_minutes",
        "final_charge_minutes",
    }.intersection(payload.model_fields_set):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employees cannot set approval, schedule, or attendance-derived leave values.",
        )
    try:
        result = _require_record(
            await use_case.update(payload.id, payload.model_dump(exclude_unset=True, exclude={"id"})),
            "Leave application date not found.",
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    await log_entity_action(
        es_client, user_id=actor_id, action="UPDATE", resource="leave_application_date",
        resource_id=payload.id, before=before, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@applications_router.delete("/dates/{date_id}", response_model=ResponseEnvelope[dict[str, bool]])
async def delete_leave_application_date(
    date_id: UUID,
    claims: dict[str, Any] = Depends(require_permission("leave.submit")),
    use_case: LeaveApplicationDateUseCase = Depends(get_leave_application_date_use_case),
    application_use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    before = _require_record(await use_case.get(date_id), "Leave application date not found.")
    parent = _require_record(
        await application_use_case.get(before.leave_application_id),
        "Leave application not found.",
    )
    if claims.get("role") != "admin" and parent.employee_id != _employee_id(claims):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update your own leave applications.")
    _require_employee_draft_application(claims, parent)
    try:
        deleted = await use_case.delete(date_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave application date not found.")
    await log_entity_action(
        es_client, user_id=actor_id, action="DELETE", resource="leave_application_date",
        resource_id=date_id, before=before, after={"deleted": True},
    )
    return ResponseEnvelope(status="success", data={"deleted": True})


@applications_router.get("/{application_id}", response_model=ResponseEnvelope[LeaveApplicationEntity])
async def get_leave_application(
    application_id: UUID,
    claims: dict[str, Any] = Depends(require_permission("leave.read_own")),
    use_case: LeaveApplicationUseCase = Depends(get_leave_application_use_case),
):
    _actor_id(claims)
    result = _require_record(await use_case.get(application_id), "Leave application not found.")
    if claims.get("role") != "admin" and result.employee_id != _employee_id(claims):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own leave applications.")
    return ResponseEnvelope(status="success", data=result)


@ledger_router.post(
    "/create",
    response_model=ResponseEnvelope[LeaveLedgerEntity],
    status_code=status.HTTP_201_CREATED,
)
async def post_leave_ledger_entry(
    payload: LeaveLedgerCreateSchema,
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
    use_case: LeaveLedgerUseCase = Depends(get_leave_ledger_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    result = await use_case.create({**payload.model_dump(), "posted_by": actor_id})
    await log_entity_action(
        es_client, user_id=actor_id, action="CREATE", resource="leave_ledger",
        resource_id=result.id, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@ledger_router.get("/list", response_model=ResponseEnvelope[list[LeaveLedgerEntity]])
async def list_leave_ledger(
    employee_id: UUID | None = None,
    leave_type_id: UUID | None = None,
    transaction_date_from: date | None = None,
    transaction_date_to: date | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
    use_case: LeaveLedgerUseCase = Depends(get_leave_ledger_use_case),
):
    _actor_id(claims)
    if (
        transaction_date_from is not None
        and transaction_date_to is not None
        and transaction_date_to < transaction_date_from
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="transaction_date_to must be on or after transaction_date_from.",
        )
    result = await use_case.list(
        employee_id,
        leave_type_id,
        transaction_date_from,
        transaction_date_to,
        offset,
        limit,
    )
    return ResponseEnvelope(status="success", data=result)


@ledger_router.get("/{entry_id}", response_model=ResponseEnvelope[LeaveLedgerEntity])
async def get_leave_ledger_entry(
    entry_id: UUID,
    claims: dict[str, Any] = Depends(require_permission("leave.manage")),
    use_case: LeaveLedgerUseCase = Depends(get_leave_ledger_use_case),
):
    _actor_id(claims)
    result = _require_record(await use_case.get(entry_id), "Leave ledger entry not found.")
    return ResponseEnvelope(status="success", data=result)
