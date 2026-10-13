import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from celery_app import app
from celery.signals import worker_ready
from redis import Redis
from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import init_db_models
from app.attendance.infrastructure.db_model import AttendanceModel, OvertimeApplicationModel
from app.attendance.application.worked_minutes import net_worked_minutes
from app.auth.infrastructure.db_model import UserModel
from app.filemaintenance.devices.infrastructure.db_model import DeviceModel
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import (
    EmployeeEntitlementModel,
    LeaveApplicationModel,
)
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel

logger = logging.getLogger(__name__)

PENDING_DEVICE_SNAPSHOT_KEY = "dashboard:pending-devices"
PENDING_DEVICE_SNAPSHOT_TASK = "app.tasks.dashboard_tasks.refresh_pending_device_snapshot"
RECENT_ATTENDANCE_SNAPSHOT_PREFIX = "dashboard:recent-attendance:v2"
RECENT_ATTENDANCE_SNAPSHOT_REFRESHED_AT_KEY = "dashboard:recent-attendance:v2:refreshed-at"
RECENT_ATTENDANCE_SNAPSHOT_TASK = "app.tasks.dashboard_tasks.refresh_recent_attendance_snapshot"
RECENT_ATTENDANCE_LIMIT = 5
LEAVE_DASHBOARD_SNAPSHOT_PREFIX = "dashboard:leave"
LEAVE_DASHBOARD_SNAPSHOT_TASK = "app.tasks.dashboard_tasks.refresh_leave_dashboard_snapshots"
LEAVE_DASHBOARD_APPLICATION_LIMIT = 5
PH_TIMEZONE = ZoneInfo("Asia/Manila")


def _cache_url() -> str:
    return settings.DASHBOARD_CACHE_REDIS_URL or f"redis://{settings.REDIS_HOST}:6379/1"


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _serialize_ph_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(PH_TIMEZONE).isoformat()


def _expected_punches(
    work_date: date,
    expected_clock_in_at: datetime | None,
    expected_clock_out_at: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    if expected_clock_in_at is None and expected_clock_out_at is None:
        return (
            datetime.combine(work_date, time(9, 0), tzinfo=PH_TIMEZONE),
            datetime.combine(work_date, time(18, 0), tzinfo=PH_TIMEZONE),
        )
    return expected_clock_in_at, expected_clock_out_at


def _load_pending_device_snapshot() -> dict[str, Any]:
    init_db_models()
    database_url = make_url(settings.DATABASE_URL)
    if database_url.drivername == "postgresql+asyncpg":
        database_url = database_url.set(drivername="postgresql+psycopg2")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        statement = (
            select(
                DeviceModel.id,
                DeviceModel.device_uuid,
                DeviceModel.device_name,
                DeviceModel.enrollment_ip,
                DeviceModel.employee_id,
                DeviceModel.platform,
                DeviceModel.manufacturer,
                DeviceModel.model,
                DeviceModel.os_version,
                DeviceModel.app_version,
                DeviceModel.registration_status,
                DeviceModel.is_active,
                DeviceModel.created_at,
                DeviceModel.last_seen_at,
                EmployeeModel.employee_no,
                EmployeeModel.first_name,
                EmployeeModel.last_name,
            )
            .outerjoin(EmployeeModel, EmployeeModel.id == DeviceModel.employee_id)
            .where(DeviceModel.registration_status == "PENDING")
            .order_by(DeviceModel.created_at.desc(), DeviceModel.device_uuid)
        )
        with Session(engine) as session:
            devices = [
                {
                    "id": str(row.id),
                    "device_uuid": row.device_uuid,
                    "device_name": row.device_name,
                    "enrollment_ip": row.enrollment_ip,
                    "employee_id": str(row.employee_id) if row.employee_id else None,
                    "employee_no": row.employee_no,
                    "employee_first_name": row.first_name,
                    "employee_last_name": row.last_name,
                    "platform": row.platform,
                    "manufacturer": row.manufacturer,
                    "model": row.model,
                    "os_version": row.os_version,
                    "app_version": row.app_version,
                    "registration_status": row.registration_status,
                    "is_active": row.is_active,
                    "created_at": _serialize_datetime(row.created_at),
                    "last_seen_at": _serialize_datetime(row.last_seen_at),
                }
                for row in session.execute(statement)
            ]
    finally:
        engine.dispose()

    return {
        "devices": devices,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }


def load_recent_attendance_snapshots(user_id: str | None = None) -> dict[str, dict[str, Any]]:
    init_db_models()
    database_url = make_url(settings.DATABASE_URL)
    if database_url.drivername == "postgresql+asyncpg":
        database_url = database_url.set(drivername="postgresql+psycopg2")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        today = datetime.now(PH_TIMEZONE).date()
        ranked_cutoffs = (
            select(
                EmploymentAssignmentModel.employee_id.label("employee_id"),
                PayrollCutoffModel.period_start.label("period_start"),
                PayrollCutoffModel.period_end.label("period_end"),
                func.row_number()
                .over(
                    partition_by=EmploymentAssignmentModel.employee_id,
                    order_by=(
                        PayrollCutoffModel.period_start.desc(),
                        PayrollCutoffModel.period_end.desc(),
                    ),
                )
                .label("cutoff_number"),
            )
            .join(
                PayrollCutoffModel,
                PayrollCutoffModel.payroll_group_id == EmploymentAssignmentModel.payroll_group_id,
            )
            .where(
                EmploymentAssignmentModel.is_active.is_(True),
                EmploymentAssignmentModel.status == "ACTIVE",
                EmploymentAssignmentModel.effective_from <= today,
                or_(
                    EmploymentAssignmentModel.effective_to.is_(None),
                    EmploymentAssignmentModel.effective_to >= today,
                ),
                PayrollCutoffModel.is_active.is_(True),
                PayrollCutoffModel.period_start <= today,
                PayrollCutoffModel.period_end >= today,
            )
            .subquery()
        )
        current_cutoff = (
            select(
                ranked_cutoffs.c.employee_id,
                ranked_cutoffs.c.period_start,
                ranked_cutoffs.c.period_end,
            )
            .where(ranked_cutoffs.c.cutoff_number == 1)
            .subquery()
        )
        ranked_records = select(
            AttendanceModel.id.label("attendance_id"),
            AttendanceModel.schedule_template_id.label("schedule_template_id"),
            AttendanceModel.user_id.label("user_id"),
            AttendanceModel.work_date.label("work_date"),
            AttendanceModel.created_at.label("created_at"),
            AttendanceModel.expected_clock_in_at.label("expected_clock_in_at"),
            AttendanceModel.expected_clock_out_at.label("expected_clock_out_at"),
            AttendanceModel.corrected_clock_in_at.label("corrected_clock_in_at"),
            AttendanceModel.clock_in_at.label("clock_in_at"),
            AttendanceModel.corrected_clock_out_at.label("corrected_clock_out_at"),
            AttendanceModel.clock_out_at.label("clock_out_at"),
            AttendanceModel.punch_metadata.label("punch_metadata"),
            AttendanceModel.is_absent.label("is_absent"),
            AttendanceModel.leave_type.label("leave_type"),
            AttendanceModel.late_minutes.label("late_minutes"),
            AttendanceModel.undertime_minutes.label("undertime_minutes"),
            AttendanceModel.calculated_ot_minutes.label("calculated_ot_minutes"),
            AttendanceModel.overtime_hours.label("overtime_hours"),
            AttendanceModel.regular_overtime_minutes.label("regular_overtime_minutes"),
            AttendanceModel.regular_overtime_hours.label("regular_overtime_hours"),
            AttendanceModel.night_differential_overtime_minutes.label("night_differential_overtime_minutes"),
            AttendanceModel.night_differential_overtime_hours.label("night_differential_overtime_hours"),
            AttendanceModel.night_differential_minutes.label("night_differential_minutes"),
            AttendanceModel.night_differential_hours.label("night_differential_hours"),
            AttendanceModel.overtime_request_status.label("overtime_request_status"),
            AttendanceModel.requested_regular_overtime_minutes.label("requested_regular_overtime_minutes"),
            AttendanceModel.requested_night_differential_overtime_minutes.label(
                "requested_night_differential_overtime_minutes"
            ),
            AttendanceModel.requested_night_differential_minutes.label(
                "requested_night_differential_minutes"
            ),
            AttendanceModel.approved_regular_overtime_minutes.label("approved_regular_overtime_minutes"),
            AttendanceModel.approved_night_differential_overtime_minutes.label(
                "approved_night_differential_overtime_minutes"
            ),
            AttendanceModel.approved_night_differential_minutes.label(
                "approved_night_differential_minutes"
            ),
            func.row_number()
            .over(
                partition_by=AttendanceModel.user_id,
                order_by=(AttendanceModel.work_date.desc(), AttendanceModel.created_at.desc()),
            )
            .label("record_number"),
        )
        ranked_records = (
            ranked_records.join(UserModel, UserModel.id == AttendanceModel.user_id)
            .join(current_cutoff, current_cutoff.c.employee_id == UserModel.employee_id)
            .where(
                AttendanceModel.record_status == "VALID",
                AttendanceModel.work_date >= current_cutoff.c.period_start,
                AttendanceModel.work_date <= current_cutoff.c.period_end,
            )
        )
        if user_id is not None:
            ranked_records = ranked_records.where(AttendanceModel.user_id == UUID(user_id))
        ranked_subquery = ranked_records.subquery()
        statement = (
            select(ranked_subquery)
            .where(ranked_subquery.c.record_number <= RECENT_ATTENDANCE_LIMIT)
            .order_by(
                ranked_subquery.c.user_id,
                ranked_subquery.c.work_date.desc(),
                ranked_subquery.c.created_at.desc(),
            )
        )
        month_start = today.replace(day=1)
        week_start = today - timedelta(days=today.weekday())
        monthly_no_login_statement = (
            select(
                AttendanceModel.user_id,
                func.count(AttendanceModel.id).label("no_login_count"),
            )
            .where(
                AttendanceModel.record_status == "VALID",
                AttendanceModel.work_date >= month_start,
                AttendanceModel.work_date <= today,
                AttendanceModel.is_absent.is_(True),
                AttendanceModel.leave_type.is_(None),
            )
            .group_by(AttendanceModel.user_id)
        )
        if user_id is not None:
            monthly_no_login_statement = monthly_no_login_statement.where(
                AttendanceModel.user_id == UUID(user_id)
            )

        weekly_statement = select(
            AttendanceModel.user_id,
            AttendanceModel.corrected_clock_in_at,
            AttendanceModel.clock_in_at,
            AttendanceModel.corrected_clock_out_at,
            AttendanceModel.clock_out_at,
            AttendanceModel.punch_metadata,
        ).where(
            AttendanceModel.record_status == "VALID",
            AttendanceModel.work_date >= week_start,
            AttendanceModel.work_date <= today,
        )
        if user_id is not None:
            weekly_statement = weekly_statement.where(AttendanceModel.user_id == UUID(user_id))

        snapshots: dict[str, dict[str, Any]] = {}
        refreshed_at = datetime.now(timezone.utc).isoformat()
        with Session(engine) as session:
            for row in session.execute(weekly_statement):
                started_at = row.corrected_clock_in_at or row.clock_in_at
                ended_at = row.corrected_clock_out_at or row.clock_out_at
                minutes_worked = net_worked_minutes(started_at, ended_at, row.punch_metadata)
                if minutes_worked is None:
                    continue
                key = str(row.user_id)
                weekly_snapshot = snapshots.setdefault(
                    key,
                    {"records": [], "refreshed_at": refreshed_at, "weekly_minutes_worked": 0},
                )
                weekly_snapshot["weekly_minutes_worked"] += minutes_worked

            attendance_rows = session.execute(statement).all()
            attendance_ids = [row.attendance_id for row in attendance_rows]
            applications_by_attendance: dict[UUID, list[dict[str, Any]]] = {}
            if attendance_ids:
                application_rows = session.execute(
                    select(OvertimeApplicationModel).where(
                        OvertimeApplicationModel.attendance_record_id.in_(attendance_ids),
                        OvertimeApplicationModel.is_active.is_(True),
                    ).order_by(
                        OvertimeApplicationModel.created_at.desc(),
                        OvertimeApplicationModel.id.desc(),
                    )
                ).scalars()
                for application in application_rows:
                    applications_by_attendance.setdefault(
                        application.attendance_record_id,
                        [],
                    ).append(
                        {
                            "id": str(application.id),
                            "application_no": application.application_no,
                            "overtime_type": application.overtime_type,
                            "requested_minutes": application.requested_minutes,
                            "supervisor_approved_minutes": application.supervisor_approved_minutes,
                            "final_payable_minutes": application.final_payable_minutes,
                            "status": application.status,
                        }
                    )

            for row in attendance_rows:
                key = str(row.user_id)
                actual_clock_in = row.corrected_clock_in_at or row.clock_in_at
                actual_clock_out = row.corrected_clock_out_at or row.clock_out_at
                expected_clock_in, expected_clock_out = _expected_punches(
                    row.work_date,
                    row.expected_clock_in_at,
                    row.expected_clock_out_at,
                )
                late_minutes = row.late_minutes
                undertime_minutes = row.undertime_minutes
                is_late = late_minutes > 0
                is_undertime = undertime_minutes > 0
                record_status = (
                    "on-leave"
                    if row.leave_type
                    else "no-login"
                    if row.is_absent
                    else "no-logout"
                    if actual_clock_in is not None and actual_clock_out is None
                    else "late"
                    if is_late
                    else "present"
                )
                snapshot = snapshots.setdefault(
                    key,
                    {"records": [], "refreshed_at": refreshed_at, "weekly_minutes_worked": 0},
                )
                snapshot["records"].append(
                    {
                        "attendance_id": str(row.attendance_id),
                        "schedule_template_id": (
                            str(row.schedule_template_id) if row.schedule_template_id else None
                        ),
                        "overtime_applications": applications_by_attendance.get(
                            row.attendance_id,
                            [],
                        ),
                        "date": row.work_date.isoformat(),
                        "expected_time_in": _serialize_ph_datetime(expected_clock_in),
                        "expected_time_out": _serialize_ph_datetime(expected_clock_out),
                        "time_in": _serialize_ph_datetime(actual_clock_in),
                        "time_out": _serialize_ph_datetime(actual_clock_out),
                        "minutes_worked": net_worked_minutes(
                            actual_clock_in, actual_clock_out, row.punch_metadata,
                        ),
                        "late_minutes": late_minutes,
                        "undertime_minutes": undertime_minutes,
                        "calculated_ot_minutes": row.calculated_ot_minutes,
                        "overtime_hours": float(row.overtime_hours),
                        "regular_overtime_minutes": row.regular_overtime_minutes,
                        "regular_overtime_hours": float(row.regular_overtime_hours),
                        "night_differential_overtime_minutes": row.night_differential_overtime_minutes,
                        "night_differential_overtime_hours": float(row.night_differential_overtime_hours),
                        "night_differential_minutes": row.night_differential_minutes,
                        "night_differential_hours": float(row.night_differential_hours),
                        "overtime_request_status": row.overtime_request_status,
                        "requested_regular_overtime_minutes": row.requested_regular_overtime_minutes,
                        "requested_night_differential_overtime_minutes": (
                            row.requested_night_differential_overtime_minutes
                        ),
                        "requested_night_differential_minutes": row.requested_night_differential_minutes,
                        "approved_regular_overtime_minutes": row.approved_regular_overtime_minutes,
                        "approved_night_differential_overtime_minutes": (
                            row.approved_night_differential_overtime_minutes
                        ),
                        "approved_night_differential_minutes": row.approved_night_differential_minutes,
                        "is_late": is_late,
                        "is_undertime": is_undertime,
                        "status": record_status,
                    }
                )
            for row in session.execute(monthly_no_login_statement):
                key = str(row.user_id)
                snapshot = snapshots.setdefault(
                    key,
                    {"records": [], "refreshed_at": refreshed_at, "weekly_minutes_worked": 0},
                )
                snapshot["missed_clock_ins_this_month"] = row.no_login_count
        for snapshot in snapshots.values():
            snapshot.setdefault("missed_clock_ins_this_month", 0)
            snapshot["weekly_hours_worked"] = round(snapshot["weekly_minutes_worked"] / 60, 2)
    finally:
        engine.dispose()

    return snapshots


def _load_leave_dashboard_snapshots(employee_id: str | None = None) -> dict[str, dict[str, Any]]:
    init_db_models()
    database_url = make_url(settings.DATABASE_URL)
    if database_url.drivername == "postgresql+asyncpg":
        database_url = database_url.set(drivername="postgresql+psycopg2")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        employee_statement = select(EmployeeModel.id).where(EmployeeModel.is_active.is_(True))
        if employee_id is not None:
            employee_statement = employee_statement.where(EmployeeModel.id == UUID(employee_id))

        current_year = datetime.now(PH_TIMEZONE).year
        entitlement_statement = (
            select(
                EmployeeEntitlementModel.employee_id,
                EmployeeEntitlementModel.leave_type_id,
                EmployeeEntitlementModel.opening_minutes,
                EmployeeEntitlementModel.granted_minutes,
                EmployeeEntitlementModel.accrued_minutes,
                EmployeeEntitlementModel.carryover_minutes,
                EmployeeEntitlementModel.adjustment_minutes,
                EmployeeEntitlementModel.used_minutes,
                EmployeeEntitlementModel.reserved_minutes,
                EmployeeEntitlementModel.expired_minutes,
                EmployeeEntitlementModel.converted_minutes,
                EmployeeEntitlementModel.available_minutes,
                EmployeeEntitlementModel.entitlement_year,
                LeaveTypeModel.leave_name,
                LeaveTypeModel.unit_type,
            )
            .join(LeaveTypeModel, LeaveTypeModel.id == EmployeeEntitlementModel.leave_type_id)
            .where(EmployeeEntitlementModel.entitlement_year == current_year)
            .order_by(LeaveTypeModel.leave_name)
        )
        application_statement = (
            select(
                LeaveApplicationModel.employee_id,
                LeaveApplicationModel.id,
                LeaveApplicationModel.application_no,
                LeaveApplicationModel.leave_type_id,
                LeaveApplicationModel.start_at,
                LeaveApplicationModel.end_at,
                LeaveApplicationModel.requested_minutes,
                LeaveApplicationModel.status,
                LeaveTypeModel.leave_name,
                LeaveTypeModel.unit_type,
            )
            .join(LeaveTypeModel, LeaveTypeModel.id == LeaveApplicationModel.leave_type_id)
            .where(LeaveApplicationModel.is_active.is_(True))
            .order_by(LeaveApplicationModel.created_at.desc(), LeaveApplicationModel.id.desc())
        )
        if employee_id is not None:
            entitlement_statement = entitlement_statement.where(EmployeeEntitlementModel.employee_id == UUID(employee_id))
            application_statement = application_statement.where(LeaveApplicationModel.employee_id == UUID(employee_id))

        refreshed_at = datetime.now(timezone.utc).isoformat()
        snapshots: dict[str, dict[str, Any]] = {}
        with Session(engine) as session:
            for row in session.execute(employee_statement):
                snapshots[str(row.id)] = {
                    "balances": [],
                    "applications": [],
                    "refreshed_at": refreshed_at,
                }
            for row in session.execute(entitlement_statement):
                key = str(row.employee_id)
                if key not in snapshots:
                    continue
                allotted_minutes = (
                    row.opening_minutes
                    + row.granted_minutes
                    + row.accrued_minutes
                    + row.carryover_minutes
                    + row.adjustment_minutes
                )
                available_minutes = (
                    allotted_minutes
                    - row.used_minutes
                    - row.reserved_minutes
                    - row.expired_minutes
                    - row.converted_minutes
                )
                snapshots[key]["balances"].append(
                    {
                        "type": str(row.leave_type_id),
                        "label": row.leave_name,
                        "unit_type": row.unit_type,
                        "allotted_minutes": allotted_minutes,
                        "used_minutes": row.used_minutes,
                        "available_minutes": available_minutes,
                        "entitlement_year": row.entitlement_year,
                    }
                )
            for row in session.execute(application_statement):
                key = str(row.employee_id)
                if key not in snapshots:
                    continue
                applications = snapshots[key]["applications"]
                if len(applications) >= LEAVE_DASHBOARD_APPLICATION_LIMIT:
                    continue
                applications.append(
                    {
                        "id": str(row.id),
                        "application_no": row.application_no,
                        "type": row.leave_name,
                        "leave_type_id": str(row.leave_type_id),
                        "unit_type": row.unit_type,
                        "requested_minutes": row.requested_minutes,
                        "start_at": _serialize_datetime(row.start_at),
                        "end_at": _serialize_datetime(row.end_at),
                        "status": row.status,
                    }
                )
    finally:
        engine.dispose()

    return snapshots


@app.task(name=PENDING_DEVICE_SNAPSHOT_TASK)
def refresh_pending_device_snapshot() -> dict[str, Any]:
    snapshot = _load_pending_device_snapshot()
    cache = Redis.from_url(_cache_url(), decode_responses=True)
    try:
        cache.set(
            PENDING_DEVICE_SNAPSHOT_KEY,
            json.dumps(snapshot),
            ex=settings.DASHBOARD_CACHE_TTL,
        )
    finally:
        cache.close()

    logger.info(
        "Refreshed pending device dashboard snapshot",
        extra={"pending_device_count": len(snapshot["devices"])},
    )
    return {
        "pending_device_count": len(snapshot["devices"]),
        "refreshed_at": snapshot["refreshed_at"],
    }


@app.task(name=RECENT_ATTENDANCE_SNAPSHOT_TASK)
def refresh_recent_attendance_snapshot(user_id: str | None = None) -> dict[str, Any]:
    snapshots = load_recent_attendance_snapshots(user_id)
    cache = Redis.from_url(_cache_url(), decode_responses=True)
    refreshed_at = datetime.now(timezone.utc).isoformat()
    try:
        with cache.pipeline() as pipeline:
            if user_id is None:
                pipeline.set(
                    RECENT_ATTENDANCE_SNAPSHOT_REFRESHED_AT_KEY,
                    refreshed_at,
                    ex=settings.DASHBOARD_CACHE_TTL,
                )
            for snapshot_user_id, snapshot in snapshots.items():
                pipeline.set(
                    f"{RECENT_ATTENDANCE_SNAPSHOT_PREFIX}:{snapshot_user_id}",
                    json.dumps(snapshot),
                    ex=settings.DASHBOARD_CACHE_TTL,
                )
            pipeline.execute()
    finally:
        cache.close()

    return {
        "user_count": len(snapshots),
        "record_count": sum(len(snapshot["records"]) for snapshot in snapshots.values()),
        "refreshed_at": refreshed_at,
    }


@app.task(name=LEAVE_DASHBOARD_SNAPSHOT_TASK)
def refresh_leave_dashboard_snapshots(employee_id: str | None = None) -> dict[str, Any]:
    snapshots = _load_leave_dashboard_snapshots(employee_id)
    cache = Redis.from_url(_cache_url(), decode_responses=True)
    try:
        with cache.pipeline() as pipeline:
            for snapshot_employee_id, snapshot in snapshots.items():
                pipeline.set(
                    f"{LEAVE_DASHBOARD_SNAPSHOT_PREFIX}:{snapshot_employee_id}",
                    json.dumps(snapshot),
                    ex=settings.DASHBOARD_CACHE_TTL,
                )
            pipeline.execute()
    finally:
        cache.close()

    logger.info(
        "Refreshed leave dashboard snapshots",
        extra={"employee_count": len(snapshots), "target_employee_id": employee_id},
    )
    return {
        "employee_count": len(snapshots),
        "application_count": sum(len(snapshot["applications"]) for snapshot in snapshots.values()),
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }


@worker_ready.connect
def refresh_pending_device_snapshot_on_worker_ready(**_kwargs: Any) -> None:
    app.send_task(PENDING_DEVICE_SNAPSHOT_TASK)
    app.send_task(RECENT_ATTENDANCE_SNAPSHOT_TASK)
    app.send_task(LEAVE_DASHBOARD_SNAPSHOT_TASK)