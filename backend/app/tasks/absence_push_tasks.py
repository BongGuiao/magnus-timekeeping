import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from celery_app import app
from app.attendance.application.automatic_absence import MANILA
from app.attendance.infrastructure.absence_alert_models import AbsenceStreakAlertModel, AbsenceStreakDismissalModel
from app.attendance.infrastructure.absence_alert_router import _visible_alerts
from app.attendance.infrastructure.absence_push_models import AbsencePushDeliveryModel, MobilePushDeviceModel
from app.auth.infrastructure.db_model import UserModel
from app.core.config import settings
from app.core.database import DATABASE_URL, init_db_models

logger = logging.getLogger(__name__)
SEND_URL = "https://exp.host/--/api/v2/push/send"
RECEIPT_URL = "https://exp.host/--/api/v2/push/getReceipts"


def _retry(delivery: AbsencePushDeliveryModel, now: datetime) -> None:
    delivery.attempts += 1
    delivery.next_attempt_at = now + timedelta(seconds=min(60 * 2 ** min(delivery.attempts - 1, 6), 3600))


async def _post(client: aiohttp.ClientSession, url: str, payload: dict) -> dict:
    headers = {"Accept": "application/json"}
    if settings.EXPO_PUSH_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {settings.EXPO_PUSH_ACCESS_TOKEN}"
    async with client.post(url, json=payload, headers=headers) as response:
        response.raise_for_status()
        data = await response.json()
    if not isinstance(data, dict) or data.get("errors"):
        raise ValueError("Expo returned an invalid response or request error.")
    return data


async def _process(session, client: aiohttp.ClientSession, delivery, device, now: datetime) -> None:
    if delivery.state == "PENDING":
        user = await session.scalar(select(UserModel.id).where(
            UserModel.id == delivery.user_id,
            UserModel.is_active.is_(True),
            UserModel.account_status == "ACTIVE",
        ))
        if user is None or device.user_id != delivery.user_id or device.session_expires_at <= now:
            delivery.state = "CANCELLED"
            return
        visibility = await _visible_alerts(session, delivery.user_id, now.astimezone(MANILA).date())
        alert = await session.scalar(select(AbsenceStreakAlertModel.id).where(
            AbsenceStreakAlertModel.id == delivery.alert_id,
            AbsenceStreakAlertModel.resolved_at.is_(None),
            visibility,
        ))
        dismissed = await session.scalar(select(AbsenceStreakDismissalModel.alert_id).where(
            AbsenceStreakDismissalModel.alert_id == delivery.alert_id,
            AbsenceStreakDismissalModel.user_id == delivery.user_id,
        ))
        if alert is None or dismissed is not None:
            delivery.state = "CANCELLED"
            return
        data = await _post(client, SEND_URL, {
            "to": device.token,
            "title": "Magnus Attendance",
            "body": "Open Magnus Attendance to view an update.",
            "sound": "default",
            "channelId": "default",
            "ttl": min(3600, max(1, int((device.session_expires_at - now).total_seconds()))),
            "collapseId": str(delivery.id),
            "tag": str(delivery.id),
        })
        ticket = data.get("data")
        if not isinstance(ticket, dict):
            raise ValueError("Expo returned an invalid push ticket.")
        if ticket.get("status") == "ok" and isinstance(ticket.get("id"), str):
            delivery.state = "RECEIPT"
            delivery.receipt_id = ticket["id"]
            delivery.sent_at = now
            delivery.attempts = 0
            delivery.next_attempt_at = now + timedelta(minutes=15)
            return
        error = ticket.get("details", {}).get("error") if isinstance(ticket.get("details"), dict) else None
        if error == "DeviceNotRegistered":
            device.session_expires_at = now
            delivery.state = "FAILED"
            logger.warning("Expo rejected an unregistered push device for delivery %s.", delivery.id)
            return
        known_error = error if error in ("MessageRateExceeded", "MessageTooBig", "InvalidCredentials") else "unknown error"
        raise ValueError(f"Expo rejected a push ticket: {known_error}.")

    if not delivery.receipt_id or not delivery.sent_at:
        raise ValueError("Push receipt state is missing its ticket or timestamp.")
    if now - delivery.sent_at >= timedelta(hours=23):
        delivery.state = "FAILED"
        logger.error("Expo push receipt expired for delivery %s.", delivery.id)
        return
    data = await _post(client, RECEIPT_URL, {"ids": [delivery.receipt_id]})
    receipts = data.get("data")
    if not isinstance(receipts, dict):
        raise ValueError("Expo returned invalid push receipts.")
    receipt = receipts.get(delivery.receipt_id)
    if receipt is None:
        delivery.next_attempt_at = now + timedelta(minutes=15)
        return
    if not isinstance(receipt, dict):
        raise ValueError("Expo returned an invalid push receipt.")
    if receipt.get("status") == "ok":
        delivery.state = "SENT"
        return
    if receipt.get("status") != "error":
        raise ValueError("Expo returned an invalid push receipt status.")
    error = receipt.get("details", {}).get("error") if isinstance(receipt.get("details"), dict) else None
    if error in ("MessageRateExceeded", "InvalidCredentials"):
        delivery.state = "PENDING"
        delivery.receipt_id = None
        delivery.sent_at = None
        _retry(delivery, now)
        logger.error("Expo push receipt for delivery %s requires retry: %s.", delivery.id, error)
        return
    if error == "DeviceNotRegistered" and device.updated_at <= delivery.sent_at:
        device.session_expires_at = now
    delivery.state = "FAILED"
    known_error = error if error in ("DeviceNotRegistered", "MessageTooBig") else "unknown error"
    logger.error("Expo push receipt failed for delivery %s: %s.", delivery.id, known_error)


async def process_absence_push_at(now: datetime) -> int:
    init_db_models()
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    processed = 0
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as client:
            for _ in range(25):
                async with factory() as session, session.begin():
                    row = (await session.execute(
                        select(AbsencePushDeliveryModel, MobilePushDeviceModel)
                        .join(MobilePushDeviceModel, MobilePushDeviceModel.id == AbsencePushDeliveryModel.device_id)
                        .where(
                            AbsencePushDeliveryModel.state.in_(("PENDING", "RECEIPT")),
                            AbsencePushDeliveryModel.next_attempt_at <= now,
                        )
                        .order_by(AbsencePushDeliveryModel.next_attempt_at, AbsencePushDeliveryModel.id)
                        .limit(1)
                        .with_for_update(of=(AbsencePushDeliveryModel, MobilePushDeviceModel), skip_locked=True)
                    )).first()
                    if row is None:
                        break
                    delivery, device = row
                    try:
                        await _process(session, client, delivery, device, now)
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
                        _retry(delivery, now)
                        status = error.status if isinstance(error, aiohttp.ClientResponseError) else None
                        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
                        logger.warning(
                            "Push delivery %s will be retried: %s (HTTP status %s).",
                            delivery.id, detail, status,
                        )
                    processed += 1
    finally:
        await engine.dispose()
    return processed


@app.task(name="app.tasks.absence_push_tasks.process_absence_push")
def process_absence_push() -> int:
    if not (settings.ABSENCE_STREAK_ALERTS_ENABLED and settings.ABSENCE_STREAK_PUSH_ENABLED):
        return 0
    return asyncio.run(process_absence_push_at(datetime.now(timezone.utc)))
