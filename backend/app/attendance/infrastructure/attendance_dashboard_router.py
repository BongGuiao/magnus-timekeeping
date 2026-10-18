from datetime import date, datetime
from typing import Literal
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
from app.attendance.application.supervisor_attendance_location_use_cases import (
    ListSupervisorAttendanceLocationsInput,
    ListSupervisorAttendanceLocationsUseCase,
    ListSupervisorTeamEmployeesInput,
    ListSupervisorTeamEmployeesUseCase,
)
from app.attendance.domain.entities.admin_dashboard import AdminDashboard, AttendanceException
from app.attendance.infrastructure.dependencies import (
    get_admin_dashboard_use_case,
    get_recent_attendance_snapshot_use_case,
    get_supervisor_attendance_locations_use_case,
    get_supervisor_team_employees_use_case,
)
from app.attendance.domain.entities.supervisor_attendance_location import (
    AmbiguousSupervisorCompanyError,
    EmployeeNotInSupervisorTeamError,
    SupervisorAttendanceLocations,
)
from app.attendance.infrastructure.http_errors import http_errors
from app.auth.infrastructure.dependencies import require_permission
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


class SupervisorAttendanceLocationRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    employee_code: str = Field(min_length=1, max_length=30)
    work_date: date


class AttendancePunchLocationSchema(BaseModel):
    attendance_id: UUID
    employee_code: str
    employee_name: str
    work_date: date
    action: Literal["CLOCK_IN", "CLOCK_OUT"]
    punched_at: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, gt=0)


class SupervisorAttendanceLocationsSchema(BaseModel):
    company_id: UUID
    employee_code: str
    work_date: date
    punches: list[AttendancePunchLocationSchema]


class SupervisorTeamEmployeeSchema(BaseModel):
    employee_id: UUID
    employee_code: str
    employee_name: str


def _supervisor_attendance_locations_schema(
    result: SupervisorAttendanceLocations,
) -> SupervisorAttendanceLocationsSchema:
    return SupervisorAttendanceLocationsSchema(
        company_id=result.company_id,
        employee_code=result.employee_code,
        work_date=result.work_date,
        punches=[
            AttendancePunchLocationSchema(
                attendance_id=punch.attendance_id,
                employee_code=punch.employee_code,
                employee_name=punch.employee_name,
                work_date=punch.work_date,
                action=punch.action,
                punched_at=punch.punched_at,
                latitude=punch.latitude,
                longitude=punch.longitude,
                accuracy_meters=punch.accuracy_meters,
            )
            for punch in result.punches
        ],
    )


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
    dependencies=[Depends(require_permission("leave.approve_team"))],
)
async def get_admin_dashboard_snapshot(
    claims: dict = Depends(require_permission("attendance.read_org")),
    use_case: GetAdminDashboardUseCase = Depends(get_admin_dashboard_use_case),
):
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
    "/team-dashboard",
    response_model=ResponseEnvelope[AdminDashboardSnapshotSchema],
    dependencies=[Depends(require_permission("leave.approve_team"))],
)
async def get_team_dashboard_snapshot(
    claims: dict = Depends(require_permission("attendance.read_team")),
    use_case: GetAdminDashboardUseCase = Depends(get_admin_dashboard_use_case),
):
    try:
        supervisor_employee_id = UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to an employee profile.",
        ) from error

    dashboard = await use_case.execute(
        GetAdminDashboardInput(supervisor_employee_id=supervisor_employee_id, team_scope=True)
    )
    return ResponseEnvelope(status="success", data=_dashboard_schema(dashboard))


@router.post(
    "/supervisor/attendance-locations",
    response_model=ResponseEnvelope[SupervisorAttendanceLocationsSchema],
)
async def get_supervisor_attendance_locations(
    request: SupervisorAttendanceLocationRequest,
    claims: dict = Depends(require_permission("attendance.read_team")),
    use_case: ListSupervisorAttendanceLocationsUseCase = Depends(
        get_supervisor_attendance_locations_use_case
    ),
):
    role_codes = claims.get("role_codes", claims.get("roles", []))
    if not isinstance(role_codes, list) or not any(
        isinstance(role_code, str) and role_code.strip().upper() == "SUPERVISOR"
        for role_code in role_codes
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This feature is available to supervisors only.",
        )
    try:
        supervisor_employee_id = UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to an employee profile.",
        ) from error

    try:
        result = await use_case.execute(
            ListSupervisorAttendanceLocationsInput(
                supervisor_employee_id=supervisor_employee_id,
                employee_code=request.employee_code,
                work_date=request.work_date,
            )
        )
    except EmployeeNotInSupervisorTeamError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except AmbiguousSupervisorCompanyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return ResponseEnvelope(status="success", data=_supervisor_attendance_locations_schema(result))


@router.get(
    "/supervisor/team-employees",
    response_model=ResponseEnvelope[list[SupervisorTeamEmployeeSchema]],
)
async def get_supervisor_team_employees(
    claims: dict = Depends(require_permission("attendance.read_team")),
    use_case: ListSupervisorTeamEmployeesUseCase = Depends(get_supervisor_team_employees_use_case),
):
    role_codes = claims.get("role_codes", claims.get("roles", []))
    if not isinstance(role_codes, list) or not any(
        isinstance(role_code, str) and role_code.strip().upper() == "SUPERVISOR"
        for role_code in role_codes
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This feature is available to supervisors only.",
        )
    try:
        supervisor_employee_id = UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to an employee profile.",
        ) from error

    employees = await use_case.execute(
        ListSupervisorTeamEmployeesInput(supervisor_employee_id=supervisor_employee_id)
    )
    return ResponseEnvelope(
        status="success",
        data=[
            SupervisorTeamEmployeeSchema(
                employee_id=employee.employee_id,
                employee_code=employee.employee_code,
                employee_name=employee.employee_name,
            )
            for employee in employees
        ],
    )


@router.get(
    "/recent",
    response_model=ResponseEnvelope[RecentAttendanceSnapshot],
)
async def get_recent_attendance_snapshot(
    force_refresh: bool = Query(default=False),
    claims: dict = Depends(require_permission("attendance.read_own")),
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
