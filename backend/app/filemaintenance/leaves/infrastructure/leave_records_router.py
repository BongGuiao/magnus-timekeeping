from datetime import date, datetime
import logging
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, status
from kombu.exceptions import OperationalError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.audit_logging import stamp_audit_fields
from app.core.config import settings
from app.core.generics.mapper import ResponseEnvelope
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
    get_employee_entitlement_use_case,
    get_leave_application_date_use_case,
    get_leave_application_use_case,
    get_leave_ledger_use_case,
)
from app.tasks.dashboard_tasks import (
    LEAVE_DASHBOARD_SNAPSHOT_PREFIX,
    refresh_leave_dashboard_snapshots,
)

entitlements_router = APIRouter(prefix="/employee-entitlements", tags=["Employee Leave Entitlements"])
applications_router = APIRouter(prefix="/leave-applications", tags=["Leave Applications"])
ledger_router = APIRouter(prefix="/leave-ledger", tags=["Leave Ledger"])
logger = logging.getLogger(__name__)
PH_TIMEZONE = ZoneInfo("Asia/Manila")


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


def _require_admin(claims: dict[str, Any]) -> None:
    if claims.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role is required to manage leave entitlements and ledger entries.",
        )


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


@entitlements_router.post(
    "/create",
    response_model=ResponseEnvelope[EmployeeEntitlementEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_employee_entitlement(
    payload: EntitlementCreateSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: EmployeeEntitlementUseCase = Depends(get_employee_entitlement_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: EmployeeEntitlementUseCase = Depends(get_employee_entitlement_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: EmployeeEntitlementUseCase = Depends(get_employee_entitlement_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.list(employee_id, leave_type_id, entitlement_year, offset, limit)
    return ResponseEnvelope(status="success", data=result)


@entitlements_router.get("/{entitlement_id}", response_model=ResponseEnvelope[EmployeeEntitlementEntity])
async def get_employee_entitlement(
    entitlement_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: EmployeeEntitlementUseCase = Depends(get_employee_entitlement_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = _require_record(await use_case.get(entitlement_id), "Employee entitlement not found.")
    return ResponseEnvelope(status="success", data=result)


@applications_router.post(
    "/create",
    response_model=ResponseEnvelope[LeaveApplicationEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_leave_application(
    payload: LeaveApplicationCreateSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
    result = await use_case.create(values)
    await log_entity_action(
        es_client, user_id=actor_id, action="CREATE", resource="leave_application",
        resource_id=result.id, after=result,
    )
    _queue_leave_dashboard_refresh(result.employee_id)
    return ResponseEnvelope(status="success", data=result)


@applications_router.put("/update", response_model=ResponseEnvelope[LeaveApplicationEntity])
async def update_leave_application(
    payload: LeaveApplicationUpdateSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
            await use_case.update_with_approval_posting(payload.id, values, actor_id),
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


@applications_router.get("/list", response_model=ResponseEnvelope[list[LeaveApplicationEntity]])
async def list_leave_applications(
    employee_id: UUID | None = None,
    leave_type_id: UUID | None = None,
    application_status: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
    result = await date_use_case.create({
        **payload.model_dump(),
        "leave_application_id": application_id,
    })
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
    result = _require_record(
        await use_case.update(payload.id, payload.model_dump(exclude_unset=True, exclude={"id"})),
        "Leave application date not found.",
    )
    await log_entity_action(
        es_client, user_id=actor_id, action="UPDATE", resource="leave_application_date",
        resource_id=payload.id, before=before, after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@applications_router.delete("/dates/{date_id}", response_model=ResponseEnvelope[dict[str, bool]])
async def delete_leave_application_date(
    date_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
    if not await use_case.delete(date_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave application date not found.")
    await log_entity_action(
        es_client, user_id=actor_id, action="DELETE", resource="leave_application_date",
        resource_id=date_id, before=before, after={"deleted": True},
    )
    return ResponseEnvelope(status="success", data={"deleted": True})


@applications_router.get("/{application_id}", response_model=ResponseEnvelope[LeaveApplicationEntity])
async def get_leave_application(
    application_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: LeaveLedgerUseCase = Depends(get_leave_ledger_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: LeaveLedgerUseCase = Depends(get_leave_ledger_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
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
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: LeaveLedgerUseCase = Depends(get_leave_ledger_use_case),
):
    _actor_id(claims)
    _require_admin(claims)
    result = _require_record(await use_case.get(entry_id), "Leave ledger entry not found.")
    return ResponseEnvelope(status="success", data=result)
