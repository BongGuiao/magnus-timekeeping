import logging
from typing import Any, Literal
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Request, status
from kombu.exceptions import OperationalError
from pydantic import BaseModel, Field, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.attendance.infrastructure.clock_policy import get_client_ip
from app.core.audit_logging import stamp_audit_fields
from app.core.config import settings
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.devices.application.device_proof import register_attendance_device
from app.filemaintenance.devices.application.use_case import (
    CreateDeviceUseCase,
    GetDeviceUseCase,
    ListDevicesUseCase,
    UpdateDeviceUseCase,
)
from app.filemaintenance.devices.domain.entities.device import DeviceEntity
from app.filemaintenance.devices.infrastructure.dependencies import (
    get_create_device_use_case,
    get_device_use_case,
    get_list_devices_use_case,
    get_update_device_use_case,
)
from app.tasks.dashboard_tasks import (
    PENDING_DEVICE_SNAPSHOT_KEY,
    refresh_pending_device_snapshot,
)

router = APIRouter(prefix="/devices", tags=["Devices"])
logger = logging.getLogger(__name__)


class AttendanceDeviceEnrollmentSchema(BaseModel):
    user_id: UUID
    device_uuid: str = Field(min_length=1, max_length=200)
    device_name: str = Field(min_length=1, max_length=100)
    public_key_jwk: dict = Field(max_length=8)
    platform: Literal["WEB", "ANDROID", "IOS"] = "WEB"
    manufacturer: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    os_version: str | None = Field(default=None, max_length=50)
    app_version: str | None = Field(default=None, max_length=50)


class AttendanceDeviceEnrollmentResult(BaseModel):
    id: UUID
    device_uuid: str
    registration_status: str


class PendingDeviceSnapshotItem(BaseModel):
    id: UUID
    device_uuid: str
    device_name: str | None
    enrollment_ip: str | None
    employee_id: UUID | None
    employee_no: str | None
    employee_first_name: str | None
    employee_last_name: str | None
    platform: str
    manufacturer: str | None
    model: str | None
    os_version: str | None
    app_version: str | None
    registration_status: str
    is_active: bool
    created_at: str | None
    last_seen_at: str | None


class PendingDeviceSnapshot(BaseModel):
    devices: list[PendingDeviceSnapshotItem]
    refreshed_at: str


def _require_email(claims: dict[str, Any]) -> None:
    if not claims.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token.",
        )


def _get_user_id(claims: dict[str, Any]) -> UUID:
    _require_email(claims)
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
            detail="Administrator role is required for device approval and management.",
        )


@router.post(
    "/enroll",
    response_model=ResponseEnvelope[AttendanceDeviceEnrollmentResult],
    status_code=status.HTTP_201_CREATED,
)
async def enroll_attendance_device(
    payload: AttendanceDeviceEnrollmentSchema,
    request: Request,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    if claims.get("role") != "admin" and actor_id != payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only register a browser for your own employee account.",
        )
    result = await register_attendance_device(
        uow,
        payload.user_id,
        payload.device_uuid,
        payload.device_name,
        payload.public_key_jwk,
        actor_id,
        manufacturer=payload.manufacturer,
        model=payload.model,
        os_version=payload.os_version,
        platform=payload.platform,
        app_version=payload.app_version,
        enrollment_ip=get_client_ip(request),
    )
    try:
        refresh_pending_device_snapshot.delay()
    except OperationalError:
        logger.exception(
            "Device enrollment saved, but the dashboard snapshot refresh could not be queued."
        )
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="device",
        resource_id=result["id"],
        after=result,
    )
    return ResponseEnvelope(
        status="success",
        data=AttendanceDeviceEnrollmentResult(**result),
    )


@router.post(
    "/create",
    response_model=ResponseEnvelope[DeviceEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_device(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateDeviceUseCase = Depends(get_create_device_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    _require_admin(claims)
    result = await use_case.execute(stamp_audit_fields(payload, actor_id, creating=True))
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="device",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[DeviceEntity],
    status_code=status.HTTP_200_OK,
)
async def update_device(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateDeviceUseCase = Depends(get_update_device_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    _require_admin(claims)
    stamp_audit_fields(payload, actor_id, creating=False)
    device_id = payload.pop("id", None)
    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Device id is required.",
        )
    try:
        parsed_device_id = UUID(str(device_id))
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Device id must be a UUID.",
        ) from error

    result = await use_case.execute(parsed_device_id, payload, actor_id)
    if "registration_status" in payload:
        try:
            refresh_pending_device_snapshot.delay()
        except OperationalError:
            logger.exception(
                "Device review saved, but the dashboard snapshot refresh could not be queued."
            )
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="device",
        resource_id=parsed_device_id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[DeviceEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_devices(
    employee_id: UUID | None = None,
    registration_status: str | None = None,
    platform: str | None = None,
    is_active: bool | None = None,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListDevicesUseCase = Depends(get_list_devices_use_case),
):
    _require_email(claims)
    result = await use_case.execute(employee_id, registration_status, platform, is_active)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/pending-snapshot",
    response_model=ResponseEnvelope[PendingDeviceSnapshot],
    status_code=status.HTTP_200_OK,
)
async def get_pending_device_snapshot(claims: dict[str, Any] = Depends(get_current_user_claims)):
    _require_admin(claims)
    cache_url = settings.DASHBOARD_CACHE_REDIS_URL or f"redis://{settings.REDIS_HOST}:6379/1"
    cache = Redis.from_url(cache_url, decode_responses=True)
    try:
        snapshot_data = await cache.get(PENDING_DEVICE_SNAPSHOT_KEY)
    except RedisError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The pending-device dashboard snapshot is temporarily unavailable.",
        ) from error
    finally:
        await cache.aclose()

    if snapshot_data is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The pending-device dashboard snapshot has not been generated yet. Please try again shortly.",
        )
    try:
        snapshot = PendingDeviceSnapshot.model_validate_json(snapshot_data)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The pending-device dashboard snapshot is invalid. Please try again after the next refresh.",
        ) from error
    return ResponseEnvelope(status="success", data=snapshot)


@router.get(
    "/{device_id}",
    response_model=ResponseEnvelope[DeviceEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_device(
    device_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetDeviceUseCase = Depends(get_device_use_case),
):
    _require_email(claims)
    result = await use_case.execute(device_id)
    return ResponseEnvelope(status="success", data=result)
