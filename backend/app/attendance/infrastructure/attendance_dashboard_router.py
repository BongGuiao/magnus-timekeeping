from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.attendance.application.admin_dashboard_use_cases import (
    GetAdminDashboardInput,
    GetAdminDashboardUseCase,
)
from app.attendance.application.recent_attendance_snapshot import RecentAttendanceSnapshot
from app.attendance.application.recent_attendance_use_cases import (
    GetRecentAttendanceSnapshotInput,
    GetRecentAttendanceSnapshotUseCase,
)
from app.attendance.domain.entities.admin_dashboard import AdminDashboard, AttendanceException
from app.attendance.infrastructure.dependencies import (
    get_admin_dashboard_use_case,
    get_recent_attendance_snapshot_use_case,
)
from app.attendance.infrastructure.http_errors import http_errors
from app.auth.domain.entities.user import Role
from app.auth.infrastructure.dependencies import get_current_user_claims, require_role
from app.core.generics.mapper import ResponseEnvelope

router = APIRouter()


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


def _exception_schema(item: AttendanceException) -> AdminAttendanceExceptionSchema:
    return AdminAttendanceExceptionSchema(
        employee_id=item.employee.id,
        employee_code=item.employee.employee_no,
        employee_name=item.employee.display_name,
        supervisor_code=item.supervisor.employee_no,
        supervisor_name=item.supervisor.display_name,
        work_date=item.work_date,
        time_in=item.time_in,
        time_out=item.time_out,
    )


def _dashboard_schema(dashboard: AdminDashboard) -> AdminDashboardSnapshotSchema:
    return AdminDashboardSnapshotSchema(
        no_login=[_exception_schema(item) for item in dashboard.no_login],
        no_logout=[_exception_schema(item) for item in dashboard.no_logout],
        pending_leaves=[
            AdminPendingLeaveSchema(
                id=leave.id,
                application_no=leave.application_no,
                employee_id=leave.employee.id,
                employee_code=leave.employee.employee_no,
                employee_name=leave.employee.display_name,
                leave_type=leave.leave_type,
                start_at=leave.start_at,
                end_at=leave.end_at,
                requested_minutes=leave.requested_minutes,
                status=leave.status,
            )
            for leave in dashboard.pending_leaves
        ],
        weekly_hours=[
            AdminWeeklyHoursSchema(
                employee_id=total.employee.id,
                employee_code=total.employee.employee_no,
                employee_name=total.employee.display_name,
                hours_worked=total.hours_worked,
                minutes_worked=total.minutes_worked,
            )
            for total in dashboard.weekly_hours
        ],
        refreshed_at=dashboard.refreshed_at,
    )


@router.get(
    "/admin-dashboard",
    response_model=ResponseEnvelope[AdminDashboardSnapshotSchema],
)
async def get_admin_dashboard_snapshot(
    claims: dict = Depends(require_role([Role.ADMIN])),
    use_case: GetAdminDashboardUseCase = Depends(get_admin_dashboard_use_case),
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

    dashboard = await use_case.execute(GetAdminDashboardInput(supervisor_employee_id=supervisor_employee_id))
    return ResponseEnvelope(status="success", data=_dashboard_schema(dashboard))


@router.get(
    "/recent",
    response_model=ResponseEnvelope[RecentAttendanceSnapshot],
)
async def get_recent_attendance_snapshot(
    force_refresh: bool = Query(default=False),
    claims: dict = Depends(get_current_user_claims),
    use_case: GetRecentAttendanceSnapshotUseCase = Depends(get_recent_attendance_snapshot_use_case),
):
    try:
        user_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error

    with http_errors():
        snapshot = await use_case.execute(
            GetRecentAttendanceSnapshotInput(user_id=user_id, force_refresh=force_refresh)
        )
    return ResponseEnvelope(status="success", data=snapshot)
