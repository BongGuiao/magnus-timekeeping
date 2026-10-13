import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from kombu.exceptions import OperationalError
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator
from elasticsearch import AsyncElasticsearch
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.orm import aliased
from geoalchemy2 import Geometry

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.domain.entities.user import Role
from app.auth.infrastructure.dependencies import get_current_user_claims, require_role
from app.auth.infrastructure.db_model import UserModel
from app.core.config import settings
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.attendance.application.use_case import (
    ClockAttendanceInputDTO,
    ClockAttendanceOutputDTO,
    ClockAttendanceUseCase,
    GetLastAttendanceInputDTO,
    GetLastAttendanceUseCase,
    LastAttendanceOutputDTO,
    RecordBreakInputDTO,
    RecordBreakOutputDTO,
    RecordBreakUseCase,
)
from app.attendance.infrastructure.dependencies import (
    get_clock_attendance_use_case,
    get_last_attendance_use_case,
    get_record_break_use_case,
)
from app.attendance.infrastructure.clock_policy import AttendanceClockPolicy, resolve_attendance_clock_policy
from app.attendance.application.worked_minutes import net_worked_minutes
from app.attendance.infrastructure.db_model import AttendanceModel, OvertimeApplicationModel
from app.attendance.infrastructure.punch_exceptions import build_punch_metadata, log_rejected_punches
from app.filemaintenance.devices.application.device_proof import (
    ChallengeAction,
    consume_device_challenge,
    issue_device_challenge,
)
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel, EmployeeWfhLocationModel
from app.filemaintenance.geofences.infrastructure.db_model import Geofence
from app.filemaintenance.location.infrastructure.db_model import Location as LocationModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import LeaveApplicationModel
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.tasks.dashboard_tasks import (
    RECENT_ATTENDANCE_SNAPSHOT_PREFIX,
    RECENT_ATTENDANCE_SNAPSHOT_REFRESHED_AT_KEY,
    load_recent_attendance_snapshots,
    refresh_recent_attendance_snapshot,
)

router = APIRouter(prefix="/attendance", tags=["Attendance"])
MAX_FACE_IMAGE_BYTES = 10 * 1024 * 1024
logger = logging.getLogger(__name__)
PH_TIMEZONE = ZoneInfo("Asia/Manila")


class DeviceChallengeRequest(BaseModel):
    user_id: UUID
    device_uuid: str = Field(min_length=1, max_length=200)
    action: ChallengeAction


class DeviceChallengeResponse(BaseModel):
    challenge_id: UUID
    message: str
    expires_at: str


class ClockPolicySchema(BaseModel):
    channel: str
    geofence_required: bool
    client_ip: str | None


@router.get("/clock-policy", response_model=ResponseEnvelope[ClockPolicySchema])
async def get_clock_policy(policy: AttendanceClockPolicy = Depends(resolve_attendance_clock_policy)):
    """Tells the client whether GPS is required for clock-in from this device/network."""
    return ResponseEnvelope[ClockPolicySchema](
        data=ClockPolicySchema(
            channel=policy.channel,
            geofence_required=policy.geofence_required,
            client_ip=policy.client_ip,
        )
    )


def get_device_security_uow() -> GenUnitOfWork:
    return get_unit_of_work()


def _authorize_challenge_user(claims: dict, requested_user_id: UUID) -> None:
    try:
        actor_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error
    if claims.get("role") != "admin" and actor_id != requested_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only request device challenges for your own employee account.",
        )


@router.post(
    "/device-challenge",
    response_model=ResponseEnvelope[DeviceChallengeResponse],
)
async def create_device_challenge(
    payload: DeviceChallengeRequest,
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_device_security_uow),
):
    _authorize_challenge_user(claims, payload.user_id)
    challenge = await issue_device_challenge(
        uow,
        payload.user_id,
        payload.device_uuid,
        payload.action,
    )
    return ResponseEnvelope(
        status="success",
        data=DeviceChallengeResponse(**challenge),
    )


async def _read_face_image(file: UploadFile) -> bytes:
    image_bytes = await file.read(MAX_FACE_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Face image is empty.")
    if len(image_bytes) > MAX_FACE_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Face image exceeds the 10 MB limit.")
    return image_bytes

class ClockResponseSchema(BaseModel):
    employee_name: str
    employee_code: str
    action: str
    timestamp: str
    schedule_template_id: UUID | None = None
    approval_required: bool = False
    late_minutes: int = 0
    undertime_minutes: int = 0
    calculated_ot_minutes: int = 0
    overtime_hours: float = 0
    regular_overtime_minutes: int = 0
    regular_overtime_hours: float = 0
    night_differential_overtime_minutes: int = 0
    night_differential_overtime_hours: float = 0
    night_differential_hours: float = 0


class SupervisorInvalidAttendanceSchema(BaseModel):
    id: UUID
    employee_id: UUID
    employee_code: str
    employee_name: str
    work_date: date
    time_in: datetime | None
    time_out: datetime | None


class LastAttendanceSchema(BaseModel):
    work_date: str
    schedule_template_id: UUID | None = None
    clock_in_at: str | None = None
    clock_out_at: str | None = None
    first_break_out_at: str | None = None
    first_break_in_at: str | None = None
    second_break_out_at: str | None = None
    second_break_in_at: str | None = None
    meal_break_out_at: str | None = None
    meal_break_in_at: str | None = None
    ot_break_out_at: str | None = None
    ot_break_in_at: str | None = None
    expected_clock_in_at: str | None = None
    expected_clock_out_at: str | None = None
    break_rules: list[dict] = Field(default_factory=list)


class RecentOvertimeApplicationSchema(BaseModel):
    id: UUID
    application_no: str
    overtime_type: Literal[
        "REGULAR_OVERTIME",
        "NIGHT_DIFFERENTIAL_OVERTIME",
        "NIGHT_DIFFERENTIAL",
    ]
    requested_minutes: int
    supervisor_approved_minutes: int | None
    final_payable_minutes: int | None
    status: str


class RecentAttendanceItemSchema(BaseModel):
    attendance_id: UUID | None = None
    schedule_template_id: UUID | None = None
    overtime_applications: list[RecentOvertimeApplicationSchema] = Field(default_factory=list)
    date: str
    expected_time_in: str | None = None
    expected_time_out: str | None = None
    time_in: str | None = None
    time_out: str | None = None
    minutes_worked: int | None = Field(default=None, ge=0)
    late_minutes: int = 0
    undertime_minutes: int = 0
    calculated_ot_minutes: int = 0
    overtime_hours: float = 0
    regular_overtime_minutes: int = 0
    regular_overtime_hours: float = 0
    night_differential_overtime_minutes: int = 0
    night_differential_overtime_hours: float = 0
    night_differential_minutes: int = 0
    night_differential_hours: float = 0
    overtime_request_status: Literal["PENDING", "APPROVED", "REJECTED"] | None = None
    requested_regular_overtime_minutes: int = 0
    requested_night_differential_overtime_minutes: int = 0
    requested_night_differential_minutes: int = 0
    approved_regular_overtime_minutes: int = 0
    approved_night_differential_overtime_minutes: int = 0
    approved_night_differential_minutes: int = 0
    is_late: bool = False
    is_undertime: bool = False
    status: Literal["present", "late", "no-login", "no-logout", "on-leave"]


class RecentAttendanceSnapshotSchema(BaseModel):
    records: list[RecentAttendanceItemSchema]
    weekly_hours_worked: float = 0
    weekly_minutes_worked: int = Field(default=0, ge=0)
    missed_clock_ins_this_month: int = 0
    refreshed_at: str


class OvertimeRequestInputSchema(BaseModel):
    regular_overtime_minutes: int = Field(default=0, ge=0)
    night_differential_overtime_minutes: int = Field(default=0, ge=0)
    night_differential_minutes: int = Field(default=0, ge=0)


class OvertimeDecisionInputSchema(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    regular_overtime_minutes: int = Field(default=0, ge=0)
    night_differential_overtime_minutes: int = Field(default=0, ge=0)
    night_differential_minutes: int = Field(default=0, ge=0)


class OvertimeRequestSchema(BaseModel):
    attendance_id: UUID
    schedule_template_id: UUID | None = None
    employee_id: UUID
    employee_code: str
    employee_name: str
    work_date: date
    calculated_regular_overtime_minutes: int
    calculated_night_differential_overtime_minutes: int
    calculated_night_differential_minutes: int
    requested_regular_overtime_minutes: int
    requested_night_differential_overtime_minutes: int
    requested_night_differential_minutes: int
    overtime_request_status: Literal["PENDING", "APPROVED", "REJECTED"] | None
    approved_regular_overtime_minutes: int
    approved_night_differential_overtime_minutes: int
    approved_night_differential_minutes: int


OvertimeApplicationType = Literal[
    "REGULAR_OVERTIME",
    "NIGHT_DIFFERENTIAL_OVERTIME",
    "NIGHT_DIFFERENTIAL",
]


class OvertimeApplicationInputSchema(BaseModel):
    overtime_type: OvertimeApplicationType
    requested_start_at: AwareDatetime | None = None
    requested_end_at: AwareDatetime | None = None
    requested_minutes: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=5000)
    work_accomplished: str | None = Field(default=None, max_length=5000)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def normalize_text(self) -> "OvertimeApplicationInputSchema":
        if self.overtime_type == "NIGHT_DIFFERENTIAL":
            raise ValueError(
                "Night-differential hours are calculated and approved automatically; "
                "a separate application is not required."
            )
        if (self.requested_start_at is None) != (self.requested_end_at is None):
            raise ValueError("Requested start and end must be supplied together.")
        if self.requested_start_at is not None and self.requested_end_at is not None:
            if self.requested_end_at <= self.requested_start_at:
                raise ValueError("Requested end must be after requested start.")
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("reason cannot be blank.")
        if self.work_accomplished is not None:
            self.work_accomplished = self.work_accomplished.strip() or None
        return self


class OvertimeApplicationDecisionSchema(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    supervisor_approved_minutes: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="forbid")


class OvertimeApplicationSchema(BaseModel):
    id: UUID
    application_no: str
    attendance_record_id: UUID
    employee_id: UUID
    employee_code: str
    employee_name: str
    attendance_date: date
    requested_start_at: datetime
    requested_end_at: datetime
    potential_ot_minutes: int
    requested_minutes: int
    system_validated_minutes: int | None
    supervisor_approved_minutes: int | None
    final_payable_minutes: int | None
    overtime_type: OvertimeApplicationType
    reason: str
    work_accomplished: str | None
    validation_status: str | None
    status: str
    payroll_posted: bool


class OvertimeCutoffSchema(BaseModel):
    cutoff_code: str
    period_start: date
    period_end: date


class OvertimeAttendanceOptionsSchema(BaseModel):
    cutoff: OvertimeCutoffSchema
    records: list[RecentAttendanceItemSchema]


def _current_overtime_cutoff_statement(employee_id: UUID, today: date):
    return (
        select(PayrollCutoffModel)
        .join(
            EmploymentAssignmentModel,
            EmploymentAssignmentModel.payroll_group_id == PayrollCutoffModel.payroll_group_id,
        )
        .where(
            EmploymentAssignmentModel.employee_id == employee_id,
            EmploymentAssignmentModel.is_active.is_(True),
            EmploymentAssignmentModel.status == "ACTIVE",
            EmploymentAssignmentModel.effective_from <= today,
            or_(EmploymentAssignmentModel.effective_to.is_(None), EmploymentAssignmentModel.effective_to >= today),
            PayrollCutoffModel.is_active.is_(True),
            PayrollCutoffModel.period_start <= today,
            PayrollCutoffModel.period_end >= today,
        )
        .order_by(PayrollCutoffModel.period_start.desc(), PayrollCutoffModel.period_end.desc(), PayrollCutoffModel.id)
        .limit(1)
    )


def _validate_overtime_cutoff(cutoff: PayrollCutoffModel | None, work_date: date | None = None) -> None:
    if cutoff is None:
        raise HTTPException(
            status_code=422,
            detail="No current payroll cutoff is configured for your active payroll assignment. Contact HR.",
        )
    if work_date is not None and not cutoff.period_start <= work_date <= cutoff.period_end:
        raise HTTPException(status_code=422, detail="Overtime attendance must be within your current payroll cutoff.")


class AdminAttendanceExceptionSchema(BaseModel):
    employee_id: UUID
    employee_code: str
    employee_name: str
    supervisor_code: str
    supervisor_name: str
    work_date: date
    time_in: datetime | None
    time_out: datetime | None


class AdminPendingLeaveSchema(BaseModel):
    id: UUID
    application_no: str
    employee_id: UUID
    employee_code: str
    employee_name: str
    leave_type: str
    start_at: datetime
    end_at: datetime
    requested_minutes: int
    status: str


class AdminWeeklyHoursSchema(BaseModel):
    employee_id: UUID
    employee_code: str
    employee_name: str
    hours_worked: float
    minutes_worked: int = Field(ge=0)


class AdminDashboardSnapshotSchema(BaseModel):
    no_login: list[AdminAttendanceExceptionSchema]
    no_logout: list[AdminAttendanceExceptionSchema]
    pending_leaves: list[AdminPendingLeaveSchema]
    weekly_hours: list[AdminWeeklyHoursSchema]
    refreshed_at: datetime


def _validate_overtime_application_period(
    requested_start_at: datetime,
    requested_end_at: datetime,
    actual_start_at: datetime,
    actual_end_at: datetime,
    requested_minutes: int,
) -> None:
    if actual_end_at <= actual_start_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The attendance record has no valid completed punch interval.",
        )
    if (
        requested_end_at <= requested_start_at
        or requested_start_at < actual_start_at
        or requested_end_at > actual_end_at
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "The overtime application period must be within the effective "
                "clock-in and clock-out times on the attendance record."
            ),
        )
    period_minutes = int((requested_end_at - requested_start_at).total_seconds() // 60)
    if requested_minutes > period_minutes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Requested minutes cannot exceed the overtime application period.",
        )


class BreakResponseSchema(BaseModel):
    employee_name: str
    employee_code: str
    action_recorded: str
    timestamp: str


@router.post(
    "/clock",
    response_model=ResponseEnvelope[ClockResponseSchema],
    status_code=status.HTTP_201_CREATED,
)
@log_rejected_punches("CLOCK")
async def clock_attendance(
    file: UploadFile = File(...),
    user_id: UUID = Form(...),
    clock_out_confirmed: bool = Form(default=False),
    latitude: float | None = Form(default=None, ge=-90, le=90),
    longitude: float | None = Form(default=None, ge=-180, le=180),
    gps_accuracy_meters: float | None = Form(default=None, gt=0),
    device_challenge_id: UUID | None = Form(default=None),
    device_signature: str | None = Form(default=None, min_length=86, max_length=86),
    policy: AttendanceClockPolicy = Depends(resolve_attendance_clock_policy),
    use_case: ClockAttendanceUseCase = Depends(get_clock_attendance_use_case),
    proof_uow: GenUnitOfWork = Depends(get_device_security_uow),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    """Records attendance after matching the captured face to the selected employee."""
    image_bytes = await _read_face_image(file)
    device_approved = False
    device_proof: dict[str, str] | None = None
    if device_challenge_id is not None and device_signature is not None:
        try:
            device_proof = await consume_device_challenge(
                proof_uow,
                user_id,
                device_challenge_id,
                "CLOCK",
                device_signature,
            )
        except ValueError as error:
            logger.warning(
                "Attendance browser proof was not approved; supervisor review is required: %s",
                error,
                extra={"user_id": str(user_id)},
            )
        else:
            device_approved = True
    else:
        logger.warning(
            "Attendance submitted without approved browser proof; supervisor review is required.",
            extra={"user_id": str(user_id)},
        )

    clock_channel = policy.as_metadata()
    if device_proof is not None:
        clock_channel.update(
            {
                "device_id": device_proof["device_id"],
                "device_uuid": device_proof["device_uuid"],
            }
        )
    input_dto = ClockAttendanceInputDTO(
        image_bytes=image_bytes,
        user_id=user_id,
        clock_out_confirmed=clock_out_confirmed,
        device_approved=device_approved,
        enforce_geofence=policy.geofence_required,
        allow_wfh=bool(
            policy.is_native
            and device_proof
            and device_proof.get("platform") in ("ANDROID", "IOS")
        ),
        clock_channel=clock_channel,
        punch_metadata={"device_proof": device_proof} if device_proof else None,
        latitude=latitude,
        longitude=longitude,
        gps_accuracy_meters=gps_accuracy_meters,
    )
    result: ClockAttendanceOutputDTO = await use_case.execute(input_dto)
    _queue_recent_attendance_refresh(user_id)
    await log_entity_action(
        es_client,
        user_id="face-recognition",
        action="CREATE",
        resource="attendance",
        resource_id=result.employee_code,
        after=result,
    )

    return ResponseEnvelope[ClockResponseSchema](
        data=ClockResponseSchema(
            employee_name=result.employee_name,
            employee_code=result.employee_code,
            action=result.action,
            timestamp=result.timestamp,
            schedule_template_id=result.schedule_template_id,
            approval_required=result.approval_required,
            late_minutes=result.late_minutes,
            undertime_minutes=result.undertime_minutes,
            calculated_ot_minutes=result.calculated_ot_minutes,
            overtime_hours=result.overtime_hours,
            regular_overtime_minutes=result.regular_overtime_minutes,
            regular_overtime_hours=result.regular_overtime_hours,
            night_differential_overtime_minutes=result.night_differential_overtime_minutes,
            night_differential_overtime_hours=result.night_differential_overtime_hours,
            night_differential_hours=result.night_differential_hours,
        )
    )

@router.post(
    "/clock-break",
    response_model=ResponseEnvelope[BreakResponseSchema],
    status_code=status.HTTP_201_CREATED,
)

@log_rejected_punches("BREAK")
async def clock_break_attendance(
    break_type: str = Form(...),
    user_id: UUID = Form(...),
    file: UploadFile = File(...),
    device_challenge_id: UUID = Form(...),
    device_signature: str = Form(..., min_length=86, max_length=86),
    latitude: float | None = Form(default=None, ge=-90, le=90),
    longitude: float | None = Form(default=None, ge=-180, le=180),
    gps_accuracy_meters: float | None = Form(default=None, gt=0),
    policy: AttendanceClockPolicy = Depends(resolve_attendance_clock_policy),
    use_case: RecordBreakUseCase = Depends(get_record_break_use_case),
    proof_uow: GenUnitOfWork = Depends(get_device_security_uow),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    """Records a break after matching the captured face to the selected employee."""
    image_bytes = await _read_face_image(file)
    device_proof = await consume_device_challenge(
        proof_uow,
        user_id,
        device_challenge_id,
        "BREAK",
        device_signature,
    )
    input_dto = RecordBreakInputDTO(
        break_type=break_type,
        user_id=user_id,
        image_bytes=image_bytes,
        device_proof=device_proof,
        punch_metadata=build_punch_metadata(
            latitude, longitude, gps_accuracy_meters, policy, datetime.now(timezone.utc),
        ),
    )
    result: RecordBreakOutputDTO = await use_case.execute(input_dto)
    _queue_recent_attendance_refresh(user_id)
    await log_entity_action(
        es_client,
        user_id="face-recognition",
        action="CREATE",
        resource="attendance_break",
        resource_id=result.employee_code,
        after=result,
    )

    return ResponseEnvelope[BreakResponseSchema](
        data=BreakResponseSchema(
            employee_name=result.employee_name,
            employee_code=result.employee_code,
            action_recorded=result.action_recorded,
            timestamp=result.timestamp,
        )
    )


def _queue_recent_attendance_refresh(user_id: UUID) -> None:
    try:
        refresh_recent_attendance_snapshot.delay(str(user_id))
    except OperationalError:
        logger.exception(
            "Attendance was saved, but its dashboard snapshot refresh could not be queued.",
            extra={"user_id": str(user_id)},
        )


@router.get(
    "/recent",
    response_model=ResponseEnvelope[RecentAttendanceSnapshotSchema],
)
async def get_recent_attendance_snapshot(
    force_refresh: bool = Query(default=False),
    claims: dict = Depends(get_current_user_claims),
):
    try:
        user_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error

    cache_url = settings.DASHBOARD_CACHE_REDIS_URL or f"redis://{settings.REDIS_HOST}:6379/1"
    cache = Redis.from_url(cache_url, decode_responses=True)
    try:
        if force_refresh:
            snapshot_key = f"{RECENT_ATTENDANCE_SNAPSHOT_PREFIX}:{user_id}"
            snapshots = await run_in_threadpool(load_recent_attendance_snapshots, str(user_id))
            snapshot_data = snapshots.get(
                str(user_id),
                {
                    "records": [],
                    "weekly_hours_worked": 0,
                    "weekly_minutes_worked": 0,
                    "missed_clock_ins_this_month": 0,
                    "refreshed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            snapshot = RecentAttendanceSnapshotSchema.model_validate(snapshot_data)
            try:
                await cache.set(
                    snapshot_key,
                    snapshot.model_dump_json(),
                    ex=settings.DASHBOARD_CACHE_TTL,
                )
                await cache.set(
                    RECENT_ATTENDANCE_SNAPSHOT_REFRESHED_AT_KEY,
                    snapshot.refreshed_at,
                    ex=settings.DASHBOARD_CACHE_TTL,
                )
            except RedisError:
                logger.exception(
                    "Fresh attendance snapshot was loaded, but its cache could not be updated.",
                    extra={"user_id": str(user_id)},
                )
            return ResponseEnvelope(status="success", data=snapshot)

        snapshot_data, refreshed_at = await cache.mget(
            f"{RECENT_ATTENDANCE_SNAPSHOT_PREFIX}:{user_id}",
            RECENT_ATTENDANCE_SNAPSHOT_REFRESHED_AT_KEY,
        )
    except RedisError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The recent attendance dashboard snapshot is temporarily unavailable.",
        ) from error
    finally:
        await cache.aclose()

    if snapshot_data is None and refreshed_at is not None:
        return ResponseEnvelope(
            status="success",
            data=RecentAttendanceSnapshotSchema(records=[], refreshed_at=refreshed_at),
        )
    if snapshot_data is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The recent attendance dashboard snapshot has not been generated yet. Please try again shortly.",
        )
    try:
        snapshot = RecentAttendanceSnapshotSchema.model_validate_json(snapshot_data)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The recent attendance dashboard snapshot is invalid. Please try again after the next refresh.",
        ) from error

    return ResponseEnvelope(status="success", data=snapshot)


@router.get(
    "/admin-dashboard",
    response_model=ResponseEnvelope[AdminDashboardSnapshotSchema],
)
async def get_admin_dashboard_snapshot(
    claims: dict = Depends(require_role([Role.ADMIN])),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    if claims.get("role") != Role.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
    try:
        supervisor_employee_id = UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to an employee profile.",
        ) from error

    today = datetime.now(PH_TIMEZONE).date()
    now_utc = datetime.now(timezone.utc)
    month_start = today.replace(day=1)
    week_start = today - timedelta(days=today.weekday())
    employee_name = func.coalesce(
        func.nullif(func.trim(EmployeeModel.preferred_name), ""),
        func.concat_ws(
            " ",
            EmployeeModel.first_name,
            EmployeeModel.middle_name,
            EmployeeModel.last_name,
            EmployeeModel.suffix,
        ),
    )
    SupervisorModel = aliased(EmployeeModel)
    supervisor_name = func.coalesce(
        func.nullif(func.trim(SupervisorModel.preferred_name), ""),
        func.concat_ws(
            " ",
            SupervisorModel.first_name,
            SupervisorModel.middle_name,
            SupervisorModel.last_name,
            SupervisorModel.suffix,
        ),
    )

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")

        attendance_rows = (
            await session.execute(
                select(
                    EmployeeModel.id.label("employee_id"),
                    EmployeeModel.employee_no.label("employee_code"),
                    employee_name.label("employee_name"),
                    SupervisorModel.employee_no.label("supervisor_code"),
                    supervisor_name.label("supervisor_name"),
                    AttendanceModel.work_date,
                    AttendanceModel.corrected_clock_in_at,
                    AttendanceModel.clock_in_at,
                    AttendanceModel.corrected_clock_out_at,
                    AttendanceModel.clock_out_at,
                    AttendanceModel.expected_clock_out_at,
                    AttendanceModel.is_absent,
                    AttendanceModel.leave_type,
                )
                .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                .join(AttendanceModel, AttendanceModel.user_id == UserModel.id)
                .join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                )
                .join(
                    SupervisorModel,
                    SupervisorModel.id == EmploymentAssignmentModel.supervisor_employee_id,
                )
                .where(
                    EmployeeModel.is_active.is_(True),
                    EmployeeModel.record_status == "ACTIVE",
                    UserModel.is_active.is_(True),
                    UserModel.account_status == "ACTIVE",
                    SupervisorModel.is_active.is_(True),
                    SupervisorModel.record_status == "ACTIVE",
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                    EmploymentAssignmentModel.effective_from <= today,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= today,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= today,
                    ),
                    AttendanceModel.record_status == "VALID",
                    AttendanceModel.work_date >= month_start,
                    AttendanceModel.work_date <= today,
                )
                .order_by(AttendanceModel.work_date.desc(), EmployeeModel.employee_no)
            )
        ).all()

        no_login: list[AdminAttendanceExceptionSchema] = []
        no_logout: list[AdminAttendanceExceptionSchema] = []
        for row in attendance_rows:
            time_in = row.corrected_clock_in_at or row.clock_in_at
            time_out = row.corrected_clock_out_at or row.clock_out_at
            record = AdminAttendanceExceptionSchema(
                employee_id=row.employee_id,
                employee_code=row.employee_code,
                employee_name=row.employee_name,
                supervisor_code=row.supervisor_code,
                supervisor_name=row.supervisor_name,
                work_date=row.work_date,
                time_in=time_in,
                time_out=time_out,
            )
            if row.leave_type:
                continue
            if row.is_absent:
                no_login.append(record)
            elif (
                time_in is not None
                and time_out is None
                and row.expected_clock_out_at is not None
                and now_utc >= row.expected_clock_out_at + timedelta(hours=6)
            ):
                no_logout.append(record)

        pending_leave_rows = (
            await session.execute(
                select(
                    LeaveApplicationModel.id,
                    LeaveApplicationModel.application_no,
                    EmployeeModel.id.label("employee_id"),
                    EmployeeModel.employee_no.label("employee_code"),
                    employee_name.label("employee_name"),
                    LeaveTypeModel.leave_name.label("leave_type"),
                    LeaveApplicationModel.start_at,
                    LeaveApplicationModel.end_at,
                    LeaveApplicationModel.requested_minutes,
                    LeaveApplicationModel.status,
                )
                .join(EmployeeModel, EmployeeModel.id == LeaveApplicationModel.employee_id)
                .join(LeaveTypeModel, LeaveTypeModel.id == LeaveApplicationModel.leave_type_id)
                .where(
                    LeaveApplicationModel.is_active.is_(True),
                    LeaveApplicationModel.status == "PENDING",
                    EmployeeModel.is_active.is_(True),
                    EmployeeModel.record_status == "ACTIVE",
                )
                .order_by(LeaveApplicationModel.start_at, EmployeeModel.employee_no)
            )
        ).all()
        pending_leaves = [AdminPendingLeaveSchema.model_validate(row._mapping) for row in pending_leave_rows]

        weekly_rows = (
            await session.execute(
                select(
                    EmployeeModel.id.label("employee_id"),
                    EmployeeModel.employee_no.label("employee_code"),
                    employee_name.label("employee_name"),
                    AttendanceModel.corrected_clock_in_at,
                    AttendanceModel.clock_in_at,
                    AttendanceModel.corrected_clock_out_at,
                    AttendanceModel.clock_out_at,
                    AttendanceModel.punch_metadata,
                )
                .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                .join(AttendanceModel, AttendanceModel.user_id == UserModel.id)
                .where(
                    EmployeeModel.is_active.is_(True),
                    EmployeeModel.record_status == "ACTIVE",
                    UserModel.is_active.is_(True),
                    UserModel.account_status == "ACTIVE",
                    AttendanceModel.record_status == "VALID",
                    AttendanceModel.work_date >= week_start,
                    AttendanceModel.work_date <= today,
                )
            )
        ).all()

        weekly_totals: dict[UUID, dict[str, str | int]] = {}
        for row in weekly_rows:
            time_in = row.corrected_clock_in_at or row.clock_in_at
            time_out = row.corrected_clock_out_at or row.clock_out_at
            minutes_worked = net_worked_minutes(time_in, time_out, row.punch_metadata)
            if minutes_worked is None:
                continue
            employee = weekly_totals.setdefault(
                row.employee_id,
                {
                    "employee_code": row.employee_code,
                    "employee_name": row.employee_name,
                    "minutes_worked": 0,
                },
            )
            employee["minutes_worked"] = int(employee["minutes_worked"]) + minutes_worked

    weekly_hours = [
        AdminWeeklyHoursSchema(
            employee_id=employee_id,
            employee_code=str(values["employee_code"]),
            employee_name=str(values["employee_name"]),
            hours_worked=round(int(values["minutes_worked"]) / 60, 2),
            minutes_worked=int(values["minutes_worked"]),
        )
        for employee_id, values in sorted(
            weekly_totals.items(),
            key=lambda item: str(item[1]["employee_code"]),
        )
    ]
    return ResponseEnvelope(
        status="success",
        data=AdminDashboardSnapshotSchema(
            no_login=no_login,
            no_logout=no_logout,
            pending_leaves=pending_leaves,
            weekly_hours=weekly_hours,
            refreshed_at=datetime.now(timezone.utc),
        ),
    )


@router.get(
    "/supervisor/invalid-attendance",
    response_model=ResponseEnvelope[list[SupervisorInvalidAttendanceSchema]],
)
async def get_supervisor_invalid_attendance(
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    is_admin = claims.get("role") == Role.ADMIN.value
    supervisor_employee_id = None
    if not is_admin:
        try:
            supervisor_employee_id = UUID(str(claims["employee_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is not linked to an employee profile.",
            ) from error

    today = datetime.now(PH_TIMEZONE).date()
    employee_name = func.coalesce(
        func.nullif(func.trim(EmployeeModel.preferred_name), ""),
        func.concat_ws(
            " ",
            EmployeeModel.first_name,
            EmployeeModel.middle_name,
            EmployeeModel.last_name,
            EmployeeModel.suffix,
        ),
    )
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        statement = (
            select(
                AttendanceModel.id,
                EmployeeModel.id.label("employee_id"),
                EmployeeModel.employee_no.label("employee_code"),
                employee_name.label("employee_name"),
                AttendanceModel.work_date,
                AttendanceModel.corrected_clock_in_at,
                AttendanceModel.clock_in_at,
                AttendanceModel.corrected_clock_out_at,
                AttendanceModel.clock_out_at,
            )
            .join(UserModel, UserModel.id == AttendanceModel.user_id)
            .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
            .where(
                EmployeeModel.is_active.is_(True),
                EmployeeModel.record_status == "ACTIVE",
                UserModel.is_active.is_(True),
                UserModel.account_status == "ACTIVE",
                AttendanceModel.record_status == "INVALID",
            )
            .order_by(AttendanceModel.work_date.desc(), EmployeeModel.employee_no)
        )
        if not is_admin:
            statement = (
                statement.join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                )
                .where(
                    EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.effective_from <= today,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= today,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= today,
                    ),
                )
                .distinct()
            )
        rows = (await session.execute(statement)).all()
        records = [
            SupervisorInvalidAttendanceSchema(
                id=row.id,
                employee_id=row.employee_id,
                employee_code=row.employee_code,
                employee_name=row.employee_name,
                work_date=row.work_date,
                time_in=row.corrected_clock_in_at or row.clock_in_at,
                time_out=row.corrected_clock_out_at or row.clock_out_at,
            )
            for row in rows
        ]
    return ResponseEnvelope(status="success", data=records)


@router.post(
    "/supervisor/invalid-attendance/{attendance_id}/approve",
    response_model=ResponseEnvelope[SupervisorInvalidAttendanceSchema],
)
async def approve_supervisor_invalid_attendance(
    attendance_id: UUID,
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    is_admin = claims.get("role") == Role.ADMIN.value
    try:
        actor_id = UUID(str(claims["sub"]))
        supervisor_employee_id = None if is_admin else UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to an employee profile.",
        ) from error

    today = datetime.now(PH_TIMEZONE).date()
    now = datetime.now(timezone.utc)
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        statement = (
            select(AttendanceModel)
            .join(UserModel, UserModel.id == AttendanceModel.user_id)
            .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
            .where(
                AttendanceModel.id == attendance_id,
                AttendanceModel.record_status == "INVALID",
                EmployeeModel.is_active.is_(True),
                EmployeeModel.record_status == "ACTIVE",
                UserModel.is_active.is_(True),
                UserModel.account_status == "ACTIVE",
            )
        )
        if not is_admin:
            statement = (
                statement.join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                )
                .where(
                    EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.effective_from <= today,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= today,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= today,
                    ),
                )
            )
        attendance = await session.scalar(statement)
        if attendance is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid attendance was not found for your assigned employees or has already been reviewed.",
            )
        attendance.record_status = "VALID"
        attendance.approved_by_id = actor_id
        attendance.approved_at = now
        attendance_user_id = attendance.user_id
        await session.flush()
        employee = await session.scalar(
            select(EmployeeModel)
            .join(UserModel, UserModel.employee_id == EmployeeModel.id)
            .where(UserModel.id == attendance.user_id)
        )
        if employee is None:
            raise RuntimeError("Attendance employee profile could not be loaded.")
        preferred_name = employee.preferred_name.strip() if employee.preferred_name else ""
        employee_name = preferred_name or " ".join(
            part
            for part in (
                employee.first_name,
                employee.middle_name,
                employee.last_name,
                employee.suffix,
            )
            if part
        )
        result = SupervisorInvalidAttendanceSchema(
            id=attendance.id,
            employee_id=employee.id,
            employee_code=employee.employee_no,
            employee_name=employee_name,
            work_date=attendance.work_date,
            time_in=attendance.corrected_clock_in_at or attendance.clock_in_at,
            time_out=attendance.corrected_clock_out_at or attendance.clock_out_at,
        )

    _queue_recent_attendance_refresh(attendance_user_id)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="APPROVE",
        resource="attendance",
        resource_id=str(attendance_id),
        after={"record_status": "VALID", "approved_at": now.isoformat()},
    )
    return ResponseEnvelope(status="success", data=result)


def _overtime_request_output(attendance: AttendanceModel, employee: EmployeeModel) -> OvertimeRequestSchema:
    preferred_name = employee.preferred_name.strip() if employee.preferred_name else ""
    employee_name = preferred_name or " ".join(
        part
        for part in (
            employee.first_name,
            employee.middle_name,
            employee.last_name,
            employee.suffix,
        )
        if part
    )
    return OvertimeRequestSchema(
        attendance_id=attendance.id,
        schedule_template_id=attendance.schedule_template_id,
        employee_id=employee.id,
        employee_code=employee.employee_no,
        employee_name=employee_name,
        work_date=attendance.work_date,
        calculated_regular_overtime_minutes=attendance.regular_overtime_minutes,
        calculated_night_differential_overtime_minutes=attendance.night_differential_overtime_minutes,
        calculated_night_differential_minutes=attendance.night_differential_minutes,
        requested_regular_overtime_minutes=attendance.requested_regular_overtime_minutes,
        requested_night_differential_overtime_minutes=(
            attendance.requested_night_differential_overtime_minutes
        ),
        requested_night_differential_minutes=attendance.requested_night_differential_minutes,
        overtime_request_status=attendance.overtime_request_status,
        approved_regular_overtime_minutes=attendance.approved_regular_overtime_minutes,
        approved_night_differential_overtime_minutes=(
            attendance.approved_night_differential_overtime_minutes
        ),
        approved_night_differential_minutes=attendance.approved_night_differential_minutes,
    )


def _overtime_application_output(
    application: OvertimeApplicationModel,
    attendance: AttendanceModel,
    employee: EmployeeModel,
) -> OvertimeApplicationSchema:
    preferred_name = employee.preferred_name.strip() if employee.preferred_name else ""
    employee_name = preferred_name or " ".join(
        part
        for part in (
            employee.first_name,
            employee.middle_name,
            employee.last_name,
            employee.suffix,
        )
        if part
    )
    return OvertimeApplicationSchema(
        id=application.id,
        application_no=application.application_no,
        attendance_record_id=attendance.id,
        employee_id=employee.id,
        employee_code=employee.employee_no,
        employee_name=employee_name,
        attendance_date=application.attendance_date,
        requested_start_at=application.requested_start_at,
        requested_end_at=application.requested_end_at,
        potential_ot_minutes=application.potential_ot_minutes,
        requested_minutes=application.requested_minutes,
        system_validated_minutes=application.system_validated_minutes,
        supervisor_approved_minutes=application.supervisor_approved_minutes,
        final_payable_minutes=application.final_payable_minutes,
        overtime_type=application.overtime_type,
        reason=application.reason,
        work_accomplished=application.work_accomplished,
        validation_status=application.validation_status,
        status=application.status,
        payroll_posted=application.payroll_posted,
    )


async def _sync_attendance_overtime_from_applications(
    session,
    attendance: AttendanceModel,
) -> None:
    applications = (
        await session.scalars(
            select(OvertimeApplicationModel)
            .where(
                OvertimeApplicationModel.attendance_record_id == attendance.id,
                OvertimeApplicationModel.is_active.is_(True),
            )
            .order_by(OvertimeApplicationModel.created_at.desc(), OvertimeApplicationModel.id.desc())
        )
    ).all()
    latest_by_type: dict[str, OvertimeApplicationModel] = {}
    for application in applications:
        latest_by_type.setdefault(application.overtime_type, application)

    category_fields = {
        "REGULAR_OVERTIME": (
            "requested_regular_overtime_minutes",
            "approved_regular_overtime_minutes",
        ),
        "NIGHT_DIFFERENTIAL_OVERTIME": (
            "requested_night_differential_overtime_minutes",
            "approved_night_differential_overtime_minutes",
        ),
        "NIGHT_DIFFERENTIAL": (
            "requested_night_differential_minutes",
            None,
        ),
    }
    statuses = []
    for overtime_type, (requested_field, approved_field) in category_fields.items():
        application = latest_by_type.get(overtime_type)
        setattr(attendance, requested_field, application.requested_minutes if application else 0)
        approved_minutes = (
            application.final_payable_minutes or 0
            if application is not None and application.status == "APPROVED"
            else 0
        )
        if approved_field is not None:
            setattr(attendance, approved_field, approved_minutes)
        if application is not None:
            statuses.append(application.status)

    if not statuses:
        attendance.overtime_request_status = None
    elif "PENDING" in statuses:
        attendance.overtime_request_status = "PENDING"
    elif "APPROVED" in statuses:
        attendance.overtime_request_status = "APPROVED"
    else:
        attendance.overtime_request_status = "REJECTED"

    attendance.approved_night_differential_minutes = attendance.night_differential_minutes
    attendance.approved_ot_worked = (
        attendance.approved_regular_overtime_minutes
        + attendance.approved_night_differential_overtime_minutes
    ) / 60
    attendance.approved_night_diff = attendance.night_differential_minutes / 60


@router.get("/overtime-attendance-options", response_model=ResponseEnvelope[OvertimeAttendanceOptionsSchema])
async def get_overtime_attendance_options(
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    try:
        user_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=401, detail="User id claim missing or invalid in authentication token.") from error
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        employee_id = await session.scalar(
            select(EmployeeModel.id)
            .join(UserModel, UserModel.employee_id == EmployeeModel.id)
            .where(UserModel.id == user_id, EmployeeModel.is_active.is_(True), EmployeeModel.record_status == "ACTIVE")
        )
        if employee_id is None:
            raise HTTPException(status_code=404, detail="An active employee linked to your account was not found.")
        cutoff = await session.scalar(_current_overtime_cutoff_statement(employee_id, datetime.now(PH_TIMEZONE).date()))
        _validate_overtime_cutoff(cutoff)
        assert cutoff is not None
        attendance_records = (await session.execute(
            select(AttendanceModel).where(
                AttendanceModel.user_id == user_id,
                AttendanceModel.record_status == "VALID",
                AttendanceModel.work_date >= cutoff.period_start,
                AttendanceModel.work_date <= cutoff.period_end,
                func.coalesce(AttendanceModel.corrected_clock_in_at, AttendanceModel.clock_in_at).is_not(None),
                func.coalesce(AttendanceModel.corrected_clock_out_at, AttendanceModel.clock_out_at)
                > func.coalesce(AttendanceModel.corrected_clock_in_at, AttendanceModel.clock_in_at),
            ).order_by(AttendanceModel.work_date.desc(), AttendanceModel.created_at.desc())
        )).scalars().all()
        records = [
            RecentAttendanceItemSchema(
                attendance_id=record.id,
                date=record.work_date.isoformat(),
                expected_time_in=record.expected_clock_in_at.isoformat() if record.expected_clock_in_at else None,
                expected_time_out=record.expected_clock_out_at.isoformat() if record.expected_clock_out_at else None,
                time_in=(record.corrected_clock_in_at or record.clock_in_at).isoformat(),
                time_out=(record.corrected_clock_out_at or record.clock_out_at).isoformat(),
                regular_overtime_minutes=record.regular_overtime_minutes,
                night_differential_overtime_minutes=record.night_differential_overtime_minutes,
                night_differential_minutes=record.night_differential_minutes,
                status="present",
            )
            for record in attendance_records
        ]
        return ResponseEnvelope(status="success", data=OvertimeAttendanceOptionsSchema(
            cutoff=OvertimeCutoffSchema(cutoff_code=cutoff.cutoff_code, period_start=cutoff.period_start, period_end=cutoff.period_end),
            records=records,
        ))


@router.post(
    "/overtime-applications/{attendance_id}",
    response_model=ResponseEnvelope[OvertimeApplicationSchema],
    status_code=status.HTTP_201_CREATED,
)
async def submit_overtime_application(
    attendance_id: UUID,
    payload: OvertimeApplicationInputSchema,
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    try:
        user_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        row = (
            await session.execute(
                select(AttendanceModel, EmployeeModel)
                .with_for_update(of=AttendanceModel)
                .join(UserModel, UserModel.id == AttendanceModel.user_id)
                .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
                .where(
                    AttendanceModel.id == attendance_id,
                    AttendanceModel.user_id == user_id,
                    AttendanceModel.record_status == "VALID",
                    or_(
                        AttendanceModel.corrected_clock_out_at.is_not(None),
                        AttendanceModel.clock_out_at.is_not(None),
                    ),
                    EmployeeModel.is_active.is_(True),
                    EmployeeModel.record_status == "ACTIVE",
                )
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Completed attendance record was not found for your account.",
            )
        attendance, employee = row
        cutoff = await session.scalar(
            _current_overtime_cutoff_statement(employee.id, datetime.now(PH_TIMEZONE).date())
        )
        _validate_overtime_cutoff(cutoff, attendance.work_date)

        active_application = await session.scalar(
            select(OvertimeApplicationModel.id)
            .where(
                OvertimeApplicationModel.attendance_record_id == attendance.id,
                OvertimeApplicationModel.is_active.is_(True),
                OvertimeApplicationModel.status.in_(("PENDING", "APPROVED")),
            )
            .limit(1)
        )
        if (
            attendance.overtime_request_status in ("PENDING", "APPROVED")
            and active_application is None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An overtime request already exists for this attendance record.",
            )
        prior_application = await session.scalar(
            select(OvertimeApplicationModel)
            .where(
                OvertimeApplicationModel.attendance_record_id == attendance.id,
                OvertimeApplicationModel.overtime_type == payload.overtime_type,
                OvertimeApplicationModel.is_active.is_(True),
                OvertimeApplicationModel.status.in_(("PENDING", "APPROVED")),
            )
            .limit(1)
        )
        if prior_application is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This overtime type already has a pending or approved application.",
            )

        available_minutes = {
            "REGULAR_OVERTIME": attendance.regular_overtime_minutes,
            "NIGHT_DIFFERENTIAL_OVERTIME": attendance.night_differential_overtime_minutes,
            "NIGHT_DIFFERENTIAL": attendance.night_differential_minutes,
        }[payload.overtime_type]
        if available_minutes <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="There are no calculated minutes available for this overtime type.",
            )
        if payload.requested_minutes > available_minutes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Requested minutes cannot exceed the calculated {available_minutes} minutes.",
            )

        actual_start = attendance.corrected_clock_in_at or attendance.clock_in_at
        actual_end = attendance.corrected_clock_out_at or attendance.clock_out_at
        if actual_start is None or actual_end is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The attendance record has no valid completed punch interval.",
            )
        if payload.requested_start_at is not None and payload.requested_end_at is not None:
            requested_start_at, requested_end_at = payload.requested_start_at, payload.requested_end_at
        elif payload.overtime_type == "NIGHT_DIFFERENTIAL":
            requested_start_at, requested_end_at = actual_start, actual_end
        elif (
            attendance.expected_clock_out_at is not None
            and actual_end > attendance.expected_clock_out_at
        ):
            requested_start_at, requested_end_at = attendance.expected_clock_out_at, actual_end
        elif (
            attendance.expected_clock_in_at is not None
            and actual_start < attendance.expected_clock_in_at
        ):
            requested_start_at, requested_end_at = actual_start, attendance.expected_clock_in_at
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No eligible overtime interval is recorded for this attendance.",
            )
        _validate_overtime_application_period(
            requested_start_at=requested_start_at,
            requested_end_at=requested_end_at,
            actual_start_at=actual_start,
            actual_end_at=actual_end,
            requested_minutes=payload.requested_minutes,
        )

        application = OvertimeApplicationModel(
            application_no=f"OT-{attendance.work_date:%Y%m%d}-{uuid4().hex[:12].upper()}",
            employee_id=employee.id,
            attendance_record_id=attendance.id,
            attendance_date=attendance.work_date,
            requested_start_at=requested_start_at,
            requested_end_at=requested_end_at,
            potential_ot_minutes=available_minutes,
            requested_minutes=payload.requested_minutes,
            system_validated_minutes=payload.requested_minutes,
            overtime_type=payload.overtime_type,
            reason=payload.reason,
            work_accomplished=payload.work_accomplished,
            validation_status="VALID",
            status="PENDING",
            created_by=user_id,
            updated_by=user_id,
        )
        session.add(application)
        await session.flush()
        await session.refresh(application)
        attendance.overtime_requested_at = datetime.now(timezone.utc)
        await _sync_attendance_overtime_from_applications(session, attendance)
        result = _overtime_application_output(application, attendance, employee)

    _queue_recent_attendance_refresh(user_id)
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="SUBMIT",
        resource="overtime_application",
        resource_id=str(application.id),
        after={
            "application_no": application.application_no,
            "attendance_record_id": str(attendance_id),
            "overtime_type": payload.overtime_type,
            "requested_minutes": payload.requested_minutes,
            "requested_start_at": application.requested_start_at.isoformat(),
            "requested_end_at": application.requested_end_at.isoformat(),
        },
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/overtime-applications",
    response_model=ResponseEnvelope[list[OvertimeApplicationSchema]],
)
async def get_my_overtime_applications(
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    try:
        user_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        statement = (
            select(OvertimeApplicationModel, AttendanceModel, EmployeeModel)
            .join(
                AttendanceModel,
                AttendanceModel.id == OvertimeApplicationModel.attendance_record_id,
            )
            .join(EmployeeModel, EmployeeModel.id == OvertimeApplicationModel.employee_id)
            .join(UserModel, UserModel.employee_id == EmployeeModel.id)
            .where(
                UserModel.id == user_id,
                OvertimeApplicationModel.is_active.is_(True),
            )
            .order_by(
                OvertimeApplicationModel.attendance_date.desc(),
                OvertimeApplicationModel.created_at.desc(),
            )
        )
        rows = (await session.execute(statement)).all()
        result = [
            _overtime_application_output(application, attendance, employee)
            for application, attendance, employee in rows
        ]
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/overtime-applications/pending",
    response_model=ResponseEnvelope[list[OvertimeApplicationSchema]],
)
async def get_pending_overtime_applications(
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    is_admin = claims.get("role") == Role.ADMIN.value
    supervisor_employee_id = None
    if not is_admin:
        try:
            supervisor_employee_id = UUID(str(claims["employee_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is not linked to a supervisor employee profile.",
            ) from error

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        statement = (
            select(OvertimeApplicationModel, AttendanceModel, EmployeeModel)
            .join(
                AttendanceModel,
                AttendanceModel.id == OvertimeApplicationModel.attendance_record_id,
            )
            .join(EmployeeModel, EmployeeModel.id == OvertimeApplicationModel.employee_id)
            .where(
                OvertimeApplicationModel.status == "PENDING",
                OvertimeApplicationModel.is_active.is_(True),
                EmployeeModel.is_active.is_(True),
                EmployeeModel.record_status == "ACTIVE",
            )
            .order_by(OvertimeApplicationModel.created_at, EmployeeModel.employee_no)
        )
        if not is_admin and supervisor_employee_id is not None:
            statement = (
                statement.join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                )
                .where(
                    EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.effective_from <= AttendanceModel.work_date,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= AttendanceModel.work_date,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= AttendanceModel.work_date,
                    ),
                )
                .distinct()
            )
        rows = (await session.execute(statement)).all()
        result = [
            _overtime_application_output(application, attendance, employee)
            for application, attendance, employee in rows
        ]
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/overtime-applications/{application_id}/decision",
    response_model=ResponseEnvelope[OvertimeApplicationSchema],
)
async def decide_overtime_application(
    application_id: UUID,
    payload: OvertimeApplicationDecisionSchema,
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    is_admin = claims.get("role") == Role.ADMIN.value
    try:
        actor_id = UUID(str(claims["sub"]))
        actor_employee_id = (
            UUID(str(claims["employee_id"]))
            if claims.get("employee_id") is not None
            else None
        )
        supervisor_employee_id = None if is_admin else actor_employee_id
        if not is_admin and supervisor_employee_id is None:
            raise ValueError("Supervisor employee id is missing.")
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to a supervisor employee profile.",
        ) from error

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        statement = (
            select(OvertimeApplicationModel, AttendanceModel, EmployeeModel)
            .with_for_update(of=(OvertimeApplicationModel, AttendanceModel))
            .join(
                AttendanceModel,
                AttendanceModel.id == OvertimeApplicationModel.attendance_record_id,
            )
            .join(EmployeeModel, EmployeeModel.id == OvertimeApplicationModel.employee_id)
            .where(
                OvertimeApplicationModel.id == application_id,
                OvertimeApplicationModel.status == "PENDING",
                OvertimeApplicationModel.is_active.is_(True),
            )
        )
        if not is_admin and supervisor_employee_id is not None:
            statement = (
                statement.join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                )
                .where(
                    EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.effective_from <= AttendanceModel.work_date,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= AttendanceModel.work_date,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= AttendanceModel.work_date,
                    ),
                )
            )
        row = (await session.execute(statement)).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending overtime application was not found for your assigned employees.",
            )
        application, attendance, employee = row
        if actor_employee_id == employee.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot approve your own overtime application.",
            )
        approved_minutes = payload.supervisor_approved_minutes
        if payload.decision == "REJECTED" and approved_minutes != 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Rejected applications must have zero approved minutes.",
            )
        if payload.decision == "APPROVED":
            if approved_minutes <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="An approved application must have positive approved minutes.",
                )
            if approved_minutes > application.requested_minutes:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Approved minutes cannot exceed the requested minutes.",
                )
        application.status = payload.decision
        application.supervisor_approved_minutes = approved_minutes
        application.final_payable_minutes = approved_minutes if payload.decision == "APPROVED" else 0
        application.updated_by = actor_id
        application.row_version += 1
        await _sync_attendance_overtime_from_applications(session, attendance)
        attendance.overtime_approved_by_id = actor_id
        attendance.overtime_approved_at = datetime.now(timezone.utc)
        await session.flush()
        result = _overtime_application_output(application, attendance, employee)
        employee_user_id = (
            await session.scalar(
                select(UserModel.id).where(UserModel.employee_id == employee.id).limit(1)
            )
        )

    if employee_user_id is not None:
        _queue_recent_attendance_refresh(employee_user_id)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action=payload.decision,
        resource="overtime_application",
        resource_id=str(application_id),
        after={
            "supervisor_approved_minutes": approved_minutes,
            "final_payable_minutes": result.final_payable_minutes,
        },
    )
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/overtime/{attendance_id}/request",
    response_model=ResponseEnvelope[OvertimeRequestSchema],
)
async def submit_overtime_request(
    attendance_id: UUID,
    payload: OvertimeRequestInputSchema,
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    try:
        user_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error
    if not any((
        payload.regular_overtime_minutes,
        payload.night_differential_overtime_minutes,
        payload.night_differential_minutes,
    )):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter at least one overtime or night-differential amount to request.",
        )
    if payload.night_differential_minutes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Night-differential hours are calculated and approved automatically; "
                "a separate request is not required."
            ),
        )

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        row = (
            await session.execute(
                select(AttendanceModel, EmployeeModel)
                .with_for_update(of=AttendanceModel)
                .join(UserModel, UserModel.id == AttendanceModel.user_id)
                .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
                .where(
                    AttendanceModel.id == attendance_id,
                    AttendanceModel.user_id == user_id,
                    AttendanceModel.record_status == "VALID",
                    AttendanceModel.clock_out_at.is_not(None),
                    EmployeeModel.is_active.is_(True),
                    EmployeeModel.record_status == "ACTIVE",
                )
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Completed attendance record was not found for your account.",
            )
        attendance, employee = row
        active_application = await session.scalar(
            select(OvertimeApplicationModel.id)
            .where(
                OvertimeApplicationModel.attendance_record_id == attendance.id,
                OvertimeApplicationModel.is_active.is_(True),
                OvertimeApplicationModel.status.in_(("PENDING", "APPROVED")),
            )
            .limit(1)
        )
        if active_application is not None or attendance.overtime_request_status in ("PENDING", "APPROVED"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This attendance record already has a pending or approved overtime request.",
            )
        limits = (
            (payload.regular_overtime_minutes, attendance.regular_overtime_minutes, "regular overtime"),
            (
                payload.night_differential_overtime_minutes,
                attendance.night_differential_overtime_minutes,
                "night-differential overtime",
            ),
            (
                payload.night_differential_minutes,
                attendance.night_differential_minutes,
                "night-differential hours",
            ),
        )
        for requested, available, label in limits:
            if requested > available:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Requested {label} cannot exceed the calculated {available} minutes.",
                )

        attendance.overtime_request_status = "PENDING"
        attendance.requested_regular_overtime_minutes = payload.regular_overtime_minutes
        attendance.requested_night_differential_overtime_minutes = (
            payload.night_differential_overtime_minutes
        )
        attendance.requested_night_differential_minutes = payload.night_differential_minutes
        attendance.overtime_requested_at = datetime.now(timezone.utc)
        attendance.approved_regular_overtime_minutes = 0
        attendance.approved_night_differential_overtime_minutes = 0
        attendance.approved_night_differential_minutes = attendance.night_differential_minutes
        attendance.overtime_approved_by_id = None
        attendance.overtime_approved_at = None
        attendance.approved_night_diff = attendance.night_differential_minutes / 60
        await session.flush()
        result = _overtime_request_output(attendance, employee)

    _queue_recent_attendance_refresh(user_id)
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="SUBMIT",
        resource="attendance_overtime",
        resource_id=str(attendance_id),
        after={
            "regular_overtime_minutes": payload.regular_overtime_minutes,
            "night_differential_overtime_minutes": payload.night_differential_overtime_minutes,
            "night_differential_minutes": payload.night_differential_minutes,
        },
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/overtime/pending",
    response_model=ResponseEnvelope[list[OvertimeRequestSchema]],
)
async def get_pending_overtime_requests(
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    is_admin = claims.get("role") == Role.ADMIN.value
    supervisor_employee_id = None
    if not is_admin:
        try:
            supervisor_employee_id = UUID(str(claims["employee_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is not linked to a supervisor employee profile.",
            ) from error

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        statement = (
            select(AttendanceModel, EmployeeModel)
            .join(UserModel, UserModel.id == AttendanceModel.user_id)
            .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
            .where(
                AttendanceModel.overtime_request_status == "PENDING",
                AttendanceModel.clock_out_at.is_not(None),
                AttendanceModel.id.not_in(
                    select(OvertimeApplicationModel.attendance_record_id).where(
                        OvertimeApplicationModel.status == "PENDING",
                        OvertimeApplicationModel.is_active.is_(True),
                    )
                ),
                EmployeeModel.is_active.is_(True),
                EmployeeModel.record_status == "ACTIVE",
            )
            .order_by(AttendanceModel.overtime_requested_at, EmployeeModel.employee_no)
        )
        if not is_admin and supervisor_employee_id is not None:
            statement = (
                statement.join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                )
                .where(
                    EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.effective_from <= AttendanceModel.work_date,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= AttendanceModel.work_date,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= AttendanceModel.work_date,
                    ),
                )
                .distinct()
            )
        rows = (await session.execute(statement)).all()
        result = [_overtime_request_output(attendance, employee) for attendance, employee in rows]
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/overtime/{attendance_id}/decision",
    response_model=ResponseEnvelope[OvertimeRequestSchema],
)
async def decide_overtime_request(
    attendance_id: UUID,
    payload: OvertimeDecisionInputSchema,
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    is_admin = claims.get("role") == Role.ADMIN.value
    try:
        actor_id = UUID(str(claims["sub"]))
        actor_employee_id = (
            UUID(str(claims["employee_id"]))
            if claims.get("employee_id") is not None
            else None
        )
        supervisor_employee_id = None if is_admin else actor_employee_id
        if not is_admin and supervisor_employee_id is None:
            raise ValueError("Supervisor employee id is missing.")
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to a supervisor employee profile.",
        ) from error

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        statement = (
            select(AttendanceModel, EmployeeModel)
            .with_for_update(of=AttendanceModel)
            .join(UserModel, UserModel.id == AttendanceModel.user_id)
            .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
            .where(
                AttendanceModel.id == attendance_id,
                AttendanceModel.overtime_request_status == "PENDING",
                AttendanceModel.clock_out_at.is_not(None),
                AttendanceModel.id.not_in(
                    select(OvertimeApplicationModel.attendance_record_id).where(
                        OvertimeApplicationModel.status == "PENDING",
                        OvertimeApplicationModel.is_active.is_(True),
                    )
                ),
                EmployeeModel.is_active.is_(True),
                EmployeeModel.record_status == "ACTIVE",
            )
        )
        if not is_admin and supervisor_employee_id is not None:
            statement = (
                statement.join(
                    EmploymentAssignmentModel,
                    EmploymentAssignmentModel.employee_id == EmployeeModel.id,
                )
                .where(
                    EmploymentAssignmentModel.supervisor_employee_id == supervisor_employee_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.effective_from <= AttendanceModel.work_date,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= AttendanceModel.work_date,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= AttendanceModel.work_date,
                    ),
                )
            )
        row = (await session.execute(statement)).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending overtime request was not found for your assigned employees.",
            )
        attendance, employee = row
        if actor_employee_id == employee.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot approve your own overtime request.",
            )
        approvals = (
            (payload.regular_overtime_minutes, attendance.requested_regular_overtime_minutes, "regular OT"),
            (
                payload.night_differential_overtime_minutes,
                attendance.requested_night_differential_overtime_minutes,
                "night-differential OT",
            ),
        )
        if payload.decision == "REJECTED" and any(amount for amount, _, _ in approvals):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Rejected overtime requests must have zero approved minutes.",
            )
        for approved, requested, label in approvals:
            if approved > requested:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Approved {label} cannot exceed the employee's requested {requested} minutes.",
                )
        if payload.decision == "APPROVED" and not any(
            approved for approved, _, _ in approvals
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Approve at least one positive amount, or reject the request.",
            )
        attendance.overtime_request_status = payload.decision
        attendance.approved_regular_overtime_minutes = payload.regular_overtime_minutes
        attendance.approved_night_differential_overtime_minutes = (
            payload.night_differential_overtime_minutes
        )
        attendance.approved_night_differential_minutes = attendance.night_differential_minutes
        attendance.overtime_approved_by_id = actor_id
        attendance.overtime_approved_at = datetime.now(timezone.utc)
        attendance.approved_ot_worked = (
            payload.regular_overtime_minutes + payload.night_differential_overtime_minutes
        ) / 60
        attendance.approved_night_diff = attendance.night_differential_minutes / 60
        employee_user_id = attendance.user_id
        await session.flush()
        result = _overtime_request_output(attendance, employee)

    _queue_recent_attendance_refresh(employee_user_id)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action=payload.decision,
        resource="attendance_overtime",
        resource_id=str(attendance_id),
        after={
            "regular_overtime_minutes": payload.regular_overtime_minutes,
            "night_differential_overtime_minutes": payload.night_differential_overtime_minutes,
            "night_differential_minutes": attendance.night_differential_minutes,
        },
    )
    return ResponseEnvelope(status="success", data=result)


class AuthorizedGeofenceSchema(BaseModel):
    geofence_id: UUID
    geofence_name: str
    shape: Literal["CIRCLE", "POLYGON"]
    latitude: float | None
    longitude: float | None
    radius_meters: float | None
    maximum_gps_accuracy_meters: int


class AuthorizedLocationSchema(BaseModel):
    company_id: UUID
    location_id: UUID
    location_code: str
    location_name: str
    geofences: list[AuthorizedGeofenceSchema]
    location_type: Literal["OFFICE", "WFH"] = "OFFICE"


@router.get("/my-locations", response_model=ResponseEnvelope[list[AuthorizedLocationSchema]])
async def get_my_attendance_locations(
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    policy: AttendanceClockPolicy = Depends(resolve_attendance_clock_policy),
):
    """Sites where the signed-in employee may punch: every active assignment's primary location.

    Informational only; the clock endpoint re-validates the GPS point server-side.
    """
    try:
        employee_id = UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to an employee profile.",
        ) from error

    today = datetime.now(PH_TIMEZONE).date()
    now_utc = datetime.now(timezone.utc)
    center = func.coalesce(
        cast(Geofence.center_point, Geometry(srid=4326)),
        func.ST_Centroid(cast(Geofence.boundary_polygon, Geometry(srid=4326))),
    )
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        location_rows = (
            await session.execute(
                select(LocationModel)
                .join(
                    EmploymentAssignmentModel,
                    and_(
                        EmploymentAssignmentModel.primary_location_id == LocationModel.id,
                        EmploymentAssignmentModel.company_id == LocationModel.company_id,
                    ),
                )
                .where(
                    EmploymentAssignmentModel.employee_id == employee_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.effective_from <= today,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= today,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= today,
                    ),
                    LocationModel.is_active.is_(True),
                    LocationModel.status == "ACTIVE",
                )
                .distinct()
                .order_by(LocationModel.location_name)
            )
        ).scalars().all()
        if not location_rows:
            return ResponseEnvelope[list[AuthorizedLocationSchema]](data=[])

        geofence_rows = (
            await session.execute(
                select(
                    Geofence,
                    func.ST_Y(center).label("latitude"),
                    func.ST_X(center).label("longitude"),
                ).where(
                    or_(
                        *(
                            and_(
                                Geofence.company_id == location.company_id,
                                Geofence.location_id == location.id,
                            )
                            for location in location_rows
                        )
                    ),
                    Geofence.is_active.is_(True),
                    Geofence.status == "ACTIVE",
                    Geofence.effective_from <= now_utc,
                    or_(Geofence.effective_to.is_(None), Geofence.effective_to >= now_utc),
                )
            )
        ).all()
        wfh = await session.get(EmployeeWfhLocationModel, employee_id) if policy.is_native else None

    fences_by_location: dict[UUID, list[AuthorizedGeofenceSchema]] = {}
    for geofence, latitude, longitude in geofence_rows:
        fences_by_location.setdefault(geofence.location_id, []).append(
            AuthorizedGeofenceSchema(
                geofence_id=geofence.id,
                geofence_name=geofence.geofence_name,
                shape="POLYGON" if geofence.boundary_polygon is not None else "CIRCLE",
                latitude=float(latitude) if latitude is not None else None,
                longitude=float(longitude) if longitude is not None else None,
                radius_meters=float(geofence.radius_meters) if geofence.radius_meters is not None else None,
                maximum_gps_accuracy_meters=geofence.maximum_gps_accuracy_meters,
            )
        )

    sites = [
        AuthorizedLocationSchema(
            company_id=location.company_id,
            location_id=location.id,
            location_code=location.location_code,
            location_name=location.location_name,
            geofences=fences_by_location.get(location.id, []),
        )
        for location in location_rows
    ]
    if wfh is not None and wfh.is_active:
        fence = next((
            fence for fence, _, _ in geofence_rows
            if fence.id == wfh.geofence_id and fence.radius_meters is not None and fence.radius_meters > 0
        ), None)
        if fence is not None:
            sites.append(AuthorizedLocationSchema(
                company_id=fence.company_id,
                location_id=employee_id,
                location_code="WFH",
                location_name="Registered WFH location",
                location_type="WFH",
                geofences=[AuthorizedGeofenceSchema(
                    geofence_id=fence.id,
                    geofence_name=fence.geofence_name,
                    shape="CIRCLE",
                    latitude=wfh.latitude,
                    longitude=wfh.longitude,
                    radius_meters=float(fence.radius_meters),
                    maximum_gps_accuracy_meters=fence.maximum_gps_accuracy_meters,
                )],
            ))
    return ResponseEnvelope[list[AuthorizedLocationSchema]](data=sites)


@router.get("/last", response_model=ResponseEnvelope[LastAttendanceSchema | None])
async def get_last_attendance(
    user_id: UUID,
    use_case: GetLastAttendanceUseCase = Depends(get_last_attendance_use_case),
):
    """Most recent attendance record for an employee; null when they have never clocked in."""
    result: LastAttendanceOutputDTO | None = await use_case.execute(GetLastAttendanceInputDTO(user_id=user_id))

    if result is None:
        return ResponseEnvelope[LastAttendanceSchema | None](data=None)

    return ResponseEnvelope[LastAttendanceSchema | None](
        data=LastAttendanceSchema(
            work_date=result.work_date,
            schedule_template_id=result.schedule_template_id,
            clock_in_at=result.clock_in_at,
            clock_out_at=result.clock_out_at,
            first_break_out_at=result.first_break_out_at,
            first_break_in_at=result.first_break_in_at,
            second_break_out_at=result.second_break_out_at,
            second_break_in_at=result.second_break_in_at,
            meal_break_out_at=result.meal_break_out_at,
            meal_break_in_at=result.meal_break_in_at,
            ot_break_out_at=result.ot_break_out_at,
            ot_break_in_at=result.ot_break_in_at,
            expected_clock_in_at=result.expected_clock_in_at,
            expected_clock_out_at=result.expected_clock_out_at,
            break_rules=result.break_rules,
        )
    )
