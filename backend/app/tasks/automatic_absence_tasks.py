import argparse
import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import DateTime, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import aliased
from sqlalchemy.pool import NullPool

from celery_app import app
from app.attendance.application.automatic_absence import (
    AUTO_ABSENCE_KEY,
    MANILA,
    active_employee_accounts,
    process_automatic_absence,
)
from app.attendance.infrastructure.db_model import AttendanceModel, OfficialBusinessRequestModel
from app.auth.infrastructure.db_model import UserModel
from app.core.database import DATABASE_URL, init_db_models
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import LeaveApplicationModel

logger = logging.getLogger(__name__)
TASK_NAME = "app.tasks.automatic_absence_tasks.refresh_automatic_absences"


async def _reconciliation_candidates(session, today: date) -> list[tuple[UUID, UUID, date]]:
    start = func.timezone("Asia/Manila", cast(AttendanceModel.work_date, DateTime))
    end = func.greatest(
        func.timezone("Asia/Manila", cast(AttendanceModel.work_date + 1, DateTime)),
        AttendanceModel.expected_clock_out_at,
    )
    exceptions = [
        exists(select(model.id).where(
            model.employee_id == UserModel.employee_id,
            model.is_active.is_(True),
            model.status == "APPROVED",
            model.start_at < end,
            model.end_at > start,
        ))
        for model in (LeaveApplicationModel, OfficialBusinessRequestModel)
    ]
    punch = aliased(AttendanceModel)
    valid_punch = exists(select(punch.id).where(
        punch.user_id == AttendanceModel.user_id,
        punch.work_date == AttendanceModel.work_date,
        punch.record_status == "VALID",
        or_(punch.clock_in_at.is_not(None), punch.corrected_clock_in_at.is_not(None)),
    ))
    rows = await session.execute(
        select(UserModel.id, EmployeeModel.id, AttendanceModel.work_date)
        .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
        .join(AttendanceModel, AttendanceModel.user_id == UserModel.id)
        .where(
            UserModel.is_active.is_(True), UserModel.account_status == "ACTIVE",
            EmployeeModel.is_active.is_(True), EmployeeModel.record_status == "ACTIVE",
            AttendanceModel.record_status == "VALID", AttendanceModel.is_absent.is_(True),
            cast(AttendanceModel.punch_metadata, JSONB).has_key(AUTO_ABSENCE_KEY),
            or_(valid_punch, *exceptions, AttendanceModel.work_date.between(today - timedelta(days=1), today)),
        ).distinct()
    )
    return list(rows.all())


async def run_absence_check(
    start: date, end: date, *, apply: bool, reconcile: bool = False,
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    if start > end or end > now.astimezone(MANILA).date():
        raise ValueError("The date range must be ordered and cannot extend into the future.")
    init_db_models()
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    counts: dict[str, int] = {}
    failures = 0
    try:
        async with factory() as session:
            accounts = await active_employee_accounts(session, start, end)
            reconciliation_candidates = (
                await _reconciliation_candidates(session, now.astimezone(MANILA).date())
                if reconcile else []
            )
        candidates = set(reconciliation_candidates)
        work_date = start
        while work_date <= end:
            candidates.update((user_id, employee_id, work_date) for user_id, employee_id in accounts)
            work_date += timedelta(days=1)
        for user_id, employee_id, work_date in sorted(candidates, key=lambda row: (row[2], str(row[0]))):
            try:
                async with factory() as session:
                    async with session.begin():
                        outcome = await process_automatic_absence(session, user_id, employee_id, work_date, now)
                        if not apply:
                            await session.rollback()
                counts[outcome] = counts.get(outcome, 0) + 1
            except Exception:
                failures += 1
                logger.exception("Automatic absence check failed for user %s on %s", user_id, work_date)
    finally:
        await engine.dispose()
    if failures:
        raise RuntimeError(f"Automatic absence check failed for {failures} employee-days; see worker logs.")
    logger.info("Automatic absence check completed: apply=%s counts=%s", apply, counts)
    return counts


@app.task(name=TASK_NAME)
def refresh_automatic_absences() -> dict[str, int]:
    if os.getenv("AUTO_ABSENCE_ENABLED", "").strip().lower() not in ("1", "true", "yes", "on"):
        return {"disabled": 1}
    today = datetime.now(timezone.utc).astimezone(MANILA).date()
    return asyncio.run(run_absence_check(today - timedelta(days=1), today, apply=True, reconcile=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or backfill automatic absences.")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true", help="Persist changes; otherwise roll back the preview.")
    args = parser.parse_args()
    print(asyncio.run(run_absence_check(args.start, args.end, apply=args.apply)))


if __name__ == "__main__":
    main()
