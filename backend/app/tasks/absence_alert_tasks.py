import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import distinct, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from celery_app import app
from app.attendance.application.automatic_absence import MANILA
from app.attendance.application.absence_push import enqueue_for_alert
from app.attendance.application.return_to_work_screening import load_current_absence_streak, review_day_status
from app.attendance.application.use_case import lock_attendance_user
from app.attendance.domain.return_to_work_screening import ReviewDayStatus
from app.attendance.infrastructure.absence_alert_models import AbsenceStreakAlertModel
from app.attendance.infrastructure.attendance_merge_queries import not_merged_source
from app.attendance.infrastructure.db_model import AttendanceModel
from app.auth.infrastructure.approval_routing import active_assignment_conditions
from app.auth.infrastructure.db_model import UserModel
from app.core.database import DATABASE_URL, init_db_models
from app.core.config import settings
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel

logger = logging.getLogger(__name__)
TASK_NAME = "app.tasks.absence_alert_tasks.refresh_absence_alerts"


async def refresh_absence_alerts_at(now: datetime) -> dict[str, int]:
    today = now.astimezone(MANILA).date()
    init_db_models()
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    counts = {"checked": 0, "created": 0, "resolved": 0}
    failures = 0
    try:
        async with factory() as session:
            absent = (await session.execute(
                select(UserModel.id, EmployeeModel.id, func.min(AttendanceModel.work_date))
                .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
                .join(AttendanceModel, AttendanceModel.user_id == UserModel.id)
                .where(
                    UserModel.is_active.is_(True), UserModel.account_status == "ACTIVE",
                    EmployeeModel.is_active.is_(True), EmployeeModel.record_status == "ACTIVE",
                    AttendanceModel.record_status == "VALID", AttendanceModel.is_absent.is_(True),
                    AttendanceModel.work_date <= today, not_merged_source(),
                )
                .group_by(UserModel.id, EmployeeModel.id)
                .having(func.count(distinct(AttendanceModel.work_date)) >= 3)
            )).all()
            unresolved = (await session.execute(
                select(UserModel.id, EmployeeModel.id, func.min(AbsenceStreakAlertModel.first_absence_date))
                .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
                .join(AbsenceStreakAlertModel, AbsenceStreakAlertModel.employee_id == EmployeeModel.id)
                .where(
                    UserModel.is_active.is_(True), UserModel.account_status == "ACTIVE",
                    EmployeeModel.is_active.is_(True), EmployeeModel.record_status == "ACTIVE",
                    AbsenceStreakAlertModel.resolved_at.is_(None),
                )
                .group_by(UserModel.id, EmployeeModel.id)
            )).all()
        candidates = {}
        for user_id, employee_id, earliest in [*absent, *unresolved]:
            key = (user_id, employee_id)
            candidates[key] = min(candidates.get(key, earliest), earliest)
        for (user_id, employee_id), earliest in candidates.items():
            try:
                async with factory() as session, session.begin():
                    await lock_attendance_user(session, user_id, employee_id)
                    alerts = list((await session.scalars(
                        select(AbsenceStreakAlertModel).where(
                            AbsenceStreakAlertModel.employee_id == employee_id,
                            AbsenceStreakAlertModel.resolved_at.is_(None),
                        )
                    )).all())
                    resolved = 0
                    for alert in alerts:
                        for work_date in (
                            alert.first_absence_date, alert.second_absence_date, alert.third_absence_date,
                        ):
                            records = list((await session.scalars(select(AttendanceModel).where(
                                AttendanceModel.user_id == user_id,
                                AttendanceModel.work_date == work_date,
                                AttendanceModel.record_status == "VALID",
                                not_merged_source(),
                            ))).all())
                            day_status = await review_day_status(session, employee_id, work_date, records, now)
                            evidence_missing = (
                                day_status == ReviewDayStatus.UNKNOWN
                                and not any(record.is_absent for record in records)
                            )
                            if evidence_missing or day_status in (
                                ReviewDayStatus.PRESENT, ReviewDayStatus.NOT_ABSENT, ReviewDayStatus.APPROVED_LEAVE,
                                ReviewDayStatus.REST_DAY, ReviewDayStatus.HOLIDAY,
                            ):
                                alert.resolved_at = now
                                resolved += 1
                                break
                    active_alerts = [alert for alert in alerts if alert.resolved_at is None]
                    streak_start = max(earliest, min(alert.third_absence_date for alert in active_alerts)) if active_alerts else earliest
                    streak = await load_current_absence_streak(session, user_id, employee_id, streak_start, today, now)
                    created = 0
                    streak_dates = set(streak)
                    already_alerted = any(
                        alert.resolved_at is None and streak_dates.intersection((
                            alert.first_absence_date, alert.second_absence_date, alert.third_absence_date,
                        ))
                        for alert in alerts
                    )
                    if len(streak) >= 3 and not already_alerted:
                        companies = list((await session.scalars(
                            select(distinct(EmploymentAssignmentModel.company_id)).where(
                                EmploymentAssignmentModel.employee_id == employee_id,
                                *active_assignment_conditions(today),
                            )
                        )).all())
                        if len(companies) != 1:
                            raise ValueError("An absence alert requires exactly one active employee company.")
                        result = await session.execute(
                            insert(AbsenceStreakAlertModel).values(
                                employee_id=employee_id, company_id=companies[0],
                                first_absence_date=streak[0], second_absence_date=streak[1],
                                third_absence_date=streak[2],
                            ).on_conflict_do_nothing(
                                index_elements=["employee_id", "first_absence_date"],
                            ).returning(AbsenceStreakAlertModel.id)
                        )
                        alert_id = result.scalar_one_or_none()
                        created = int(alert_id is not None)
                        if alert_id is not None and settings.ABSENCE_STREAK_PUSH_ENABLED:
                            await enqueue_for_alert(session, alert_id, now, today)
                counts["checked"] += 1
                counts["created"] += created
                counts["resolved"] += resolved
            except Exception:
                failures += 1
                logger.exception("Absence alert screening failed for user %s", user_id)
    finally:
        await engine.dispose()
    if failures:
        raise RuntimeError(f"Absence alert screening failed for {failures} users; see worker logs.")
    logger.info("Absence alert screening completed: %s", counts)
    return counts


@app.task(name=TASK_NAME)
def refresh_absence_alerts() -> dict[str, int]:
    if not settings.ABSENCE_STREAK_ALERTS_ENABLED:
        return {"disabled": 1}
    return asyncio.run(refresh_absence_alerts_at(datetime.now(timezone.utc)))
