from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from app.attendance.application.automatic_absence import MANILA
from app.attendance.application.absence_push import enqueue_for_device
from app.attendance.infrastructure.absence_alert_router import _actor_id, _visible_alerts
from app.attendance.infrastructure.absence_push_models import MobilePushDeviceModel
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.config import settings
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work

router = APIRouter(prefix="/absence-push", tags=["Absence push notifications"])


class PushDevice(BaseModel):
    token: str = Field(max_length=255, pattern=r"^(ExponentPushToken|ExpoPushToken)\[[A-Za-z0-9_-]+\]$")


@router.get("/config", response_model=ResponseEnvelope[bool])
async def push_config(response: Response, _claims: dict = Depends(get_current_user_claims)):
    response.headers["Cache-Control"] = "no-store"
    return ResponseEnvelope(data=settings.ABSENCE_STREAK_ALERTS_ENABLED and settings.ABSENCE_STREAK_PUSH_ENABLED)


@router.post("/register", response_model=ResponseEnvelope[bool])
async def register_push_device(
    device: PushDevice,
    response: Response,
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    response.headers["Cache-Control"] = "no-store"
    if not (settings.ABSENCE_STREAK_ALERTS_ENABLED and settings.ABSENCE_STREAK_PUSH_ENABLED):
        raise HTTPException(status_code=404, detail="Absence push notifications are disabled.")
    user_id = _actor_id(claims)
    try:
        expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError, OSError) as error:
        raise HTTPException(status_code=401, detail="Invalid session expiry.") from error
    now = datetime.now(timezone.utc)
    if expires_at <= now:
        raise HTTPException(status_code=401, detail="Token has expired")
    async with uow as active:
        if active.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        await _visible_alerts(active.session, user_id, now.astimezone(MANILA).date())
        statement = insert(MobilePushDeviceModel).values(
            user_id=user_id, token=device.token, session_expires_at=expires_at, updated_at=now,
        )
        device_id = await active.session.scalar(
            statement.on_conflict_do_update(
                index_elements=["token"],
                set_={"user_id": user_id, "session_expires_at": expires_at, "updated_at": now},
            ).returning(MobilePushDeviceModel.id)
        )
        if device_id is None:
            raise RuntimeError("Could not register push device.")
        await enqueue_for_device(active.session, user_id, device_id, now.astimezone(MANILA).date())
    return ResponseEnvelope(data=True)


@router.post("/unregister", response_model=ResponseEnvelope[bool])
async def unregister_push_device(
    device: PushDevice,
    response: Response,
    claims: dict = Depends(get_current_user_claims),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    response.headers["Cache-Control"] = "no-store"
    user_id = _actor_id(claims)
    async with uow as active:
        if active.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        await active.session.execute(
            update(MobilePushDeviceModel).where(
                MobilePushDeviceModel.token == device.token, MobilePushDeviceModel.user_id == user_id,
            ).values(session_expires_at=datetime.now(timezone.utc))
        )
    return ResponseEnvelope(data=True)
