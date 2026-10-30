import base64
import binascii
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from elasticsearch import AsyncElasticsearch
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.attendance.application.offline import PrepareOfflineAttendanceUseCase, SyncOfflineAttendanceUseCase
from app.attendance.domain.offline import OFFLINE_ACTIONS
from app.attendance.infrastructure.offline_gateway import SqlAlchemyOfflineAttendanceGateway, event_result, photo_cipher
from app.attendance.infrastructure.offline_models import OfflinePunchEventModel
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.attendance.infrastructure.overtime_adapters import CeleryRecentAttendanceRefresher, ElasticsearchAuditTrail
from app.core import face_recognition_service
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.devices.application.device_proof import consume_device_challenge

router = APIRouter(prefix="/offline")


class PrepareSchema(BaseModel):
    device_uuid: str = Field(min_length=1, max_length=200)
    challenge_id: UUID
    signature: str = Field(min_length=86, max_length=86)


class EventSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    event_id: UUID
    user_id: UUID
    device_uuid: str = Field(min_length=1, max_length=200)
    permit_token: str = Field(max_length=4096)
    action: str = Field(max_length=40)
    sequence: int = Field(gt=0)
    captured_at: datetime
    gps_at: datetime
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy: float = Field(gt=0, allow_inf_nan=False)
    photo_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    previous_at: datetime | None
    clock_trusted: bool


class UploadSchema(BaseModel):
    payload_json: str = Field(max_length=16384)
    signature: str = Field(min_length=86, max_length=86)
    photo_base64: str = Field(min_length=1, max_length=13981016)


def _actor(claims: dict) -> UUID:
    try:
        if not claims.get("employee_id"):
            raise ValueError("Missing employee")
        return UUID(claims["sub"])
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(403, "An authenticated employee account is required.") from error


def _admin(claims: dict) -> UUID:
    if claims.get("role") != "admin":
        raise HTTPException(403, "Administrator access is required for offline punch review.")
    return UUID(claims["sub"])


def _gateway(uow: GenUnitOfWork = Depends(get_unit_of_work)):
    return SqlAlchemyOfflineAttendanceGateway(uow, face_recognition_service)


@router.post("/prepare")
async def prepare_offline(
    payload: PrepareSchema, claims: dict = Depends(get_current_user_claims),
    gateway: SqlAlchemyOfflineAttendanceGateway = Depends(_gateway),
):
    actor = _actor(claims)
    proof = await consume_device_challenge(
        get_unit_of_work(), actor, payload.challenge_id, "CLOCK", payload.signature,
    )
    if proof["device_uuid"] != payload.device_uuid or proof["platform"] not in ("ANDROID", "IOS"):
        raise HTTPException(403, "Offline authorization requires this approved native device.")
    result = await PrepareOfflineAttendanceUseCase(gateway).execute(actor, payload.device_uuid)
    return ResponseEnvelope(data=result)


@router.post("/sync")
async def sync_offline(
    upload: UploadSchema,
    claims: dict = Depends(get_current_user_claims),
    gateway: SqlAlchemyOfflineAttendanceGateway = Depends(_gateway),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    try:
        payload = EventSchema.model_validate_json(upload.payload_json)
    except ValidationError as error:
        raise HTTPException(422, "Invalid offline event shape or GPS evidence.") from error
    if payload.action not in OFFLINE_ACTIONS:
        raise HTTPException(422, "Unknown offline attendance action.")
    try:
        image = base64.b64decode(upload.photo_base64, validate=True)
    except binascii.Error as error:
        raise HTTPException(422, "Invalid offline photo encoding.") from error
    if not image or len(image) > 10 * 1024 * 1024:
        raise HTTPException(413, "Offline photo must contain 1 byte to 10 MB.")
    result = await SyncOfflineAttendanceUseCase(gateway, CeleryRecentAttendanceRefresher(), ElasticsearchAuditTrail(es_client)).execute(
        _actor(claims), upload.payload_json, upload.signature, image,
    )
    return ResponseEnvelope(data=result)


@router.get("/events")
async def list_offline_events(
    review: bool = False, limit: int = 50, offset: int = 0,
    claims: dict = Depends(get_current_user_claims), uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    actor = _admin(claims) if review else _actor(claims)
    async with uow:
        if uow.session is None:
            raise RuntimeError("Offline review requires an active transaction.")
        statement = select(OfflinePunchEventModel)
        if review:
            statement = statement.where(OfflinePunchEventModel.status == "NEEDS_REVIEW",
                                        OfflinePunchEventModel.reviewed_at.is_(None))
        else:
            statement = statement.where(OfflinePunchEventModel.user_id == actor)
        events = (await uow.session.scalars(statement.order_by(OfflinePunchEventModel.received_at.desc())
                                         .limit(min(max(limit, 1), 100)).offset(max(offset, 0)))).all()
        return ResponseEnvelope(data=[{
            **event_result(event), "user_id": str(event.user_id), "action": event.payload["action"],
            "payload": {key: event.payload.get(key) for key in (
                "device_uuid", "latitude", "longitude", "accuracy", "gps_at", "clock_trusted",
            )}, "review_notes": event.review_notes,
        } for event in events])


class ReviewSchema(BaseModel):
    notes: str = Field(min_length=1, max_length=2000)


@router.post("/events/{event_id}/review")
async def review_offline_event(
    event_id: UUID, payload: ReviewSchema, claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    actor = _admin(claims)
    if not payload.notes.strip():
        raise HTTPException(422, "Review notes are required.")
    async with uow:
        if uow.session is None:
            raise RuntimeError("Offline review requires an active transaction.")
        event = await uow.session.scalar(select(OfflinePunchEventModel)
                                         .where(OfflinePunchEventModel.id == event_id).with_for_update())
        if event is None:
            raise HTTPException(404, "Offline event not found.")
        if event.status != "NEEDS_REVIEW" or event.reviewed_at:
            raise HTTPException(409, "This event does not require review.")
        event.reviewed_by, event.reviewed_at = actor, datetime.now(timezone.utc)
        event.review_notes = payload.notes.strip()
        event.encrypted_photo = None
        return ResponseEnvelope(data=event_result(event))


@router.get("/events/{event_id}/photo")
async def offline_event_photo(
    event_id: UUID, claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    _admin(claims)
    async with uow:
        if uow.session is None:
            raise RuntimeError("Offline review requires an active transaction.")
        event = await uow.session.get(OfflinePunchEventModel, event_id)
        if event is None or event.encrypted_photo is None:
            raise HTTPException(404, "No retained review photo is available.")
        return Response(photo_cipher().decrypt(event.encrypted_photo), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})
