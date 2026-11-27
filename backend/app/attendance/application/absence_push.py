from datetime import date, datetime
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.infrastructure.absence_alert_models import AbsenceStreakAlertModel, AbsenceStreakDismissalModel
from app.attendance.infrastructure.absence_alert_router import _visible_alerts
from app.attendance.infrastructure.absence_push_models import AbsencePushDeliveryModel, MobilePushDeviceModel
from app.auth.infrastructure.db_model import UserModel


async def enqueue_for_device(
    session: AsyncSession, user_id: UUID, device_id: UUID, today: date, alert_id: UUID | None = None,
) -> None:
    visibility = await _visible_alerts(session, user_id, today)
    query = select(AbsenceStreakAlertModel.id).where(
        AbsenceStreakAlertModel.resolved_at.is_(None),
        visibility,
        ~exists(select(AbsenceStreakDismissalModel.alert_id).where(
            AbsenceStreakDismissalModel.alert_id == AbsenceStreakAlertModel.id,
            AbsenceStreakDismissalModel.user_id == user_id,
        )),
    )
    if alert_id is not None:
        query = query.where(AbsenceStreakAlertModel.id == alert_id)
    alert_ids = (await session.scalars(query)).all()
    if alert_ids:
        await session.execute(
            insert(AbsencePushDeliveryModel).values([
                {"alert_id": item, "user_id": user_id, "device_id": device_id} for item in alert_ids
            ]).on_conflict_do_nothing(index_elements=["alert_id", "user_id", "device_id"])
        )


async def enqueue_for_alert(session: AsyncSession, alert_id: UUID, now: datetime, today: date) -> None:
    devices = (await session.execute(
        select(MobilePushDeviceModel.id, MobilePushDeviceModel.user_id)
        .join(UserModel, UserModel.id == MobilePushDeviceModel.user_id)
        .where(
            MobilePushDeviceModel.session_expires_at > now,
            UserModel.is_active.is_(True),
            UserModel.account_status == "ACTIVE",
        )
    )).all()
    for device_id, user_id in devices:
        await enqueue_for_device(session, user_id, device_id, today, alert_id)
