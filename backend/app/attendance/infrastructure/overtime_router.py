from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.attendance.application.overtime_use_cases import (
    DecideOvertimeApplicationInput,
    DecideOvertimeApplicationUseCase,
    GetOvertimeAttendanceOptionsInput,
    GetOvertimeAttendanceOptionsUseCase,
    ListMyOvertimeApplicationsInput,
    ListMyOvertimeApplicationsUseCase,
    ListPendingOvertimeApplicationsInput,
    ListPendingOvertimeApplicationsUseCase,
    RecalculateAttendanceRangeInput,
    RecalculateAttendanceRangeUseCase,
    SubmitOvertimeApplicationInput,
    SubmitOvertimeApplicationUseCase,
    UpdateOvertimeApplicationInput,
    UpdateOvertimeApplicationUseCase,
)
from app.attendance.application.clock import ph_today, utc_now
from app.attendance.application.supervisor_attendance_location_use_cases import (
    ListSupervisorTeamEmployeesInput,
    ListSupervisorTeamEmployeesUseCase,
)
from app.attendance.application.recent_attendance_snapshot import RecentAttendanceItem
from app.attendance.domain.entities.overtime import OvertimeApplicationRecord, OvertimeAttendance
from app.attendance.infrastructure.dependencies import (
    get_decide_overtime_application_use_case,
    get_list_my_overtime_applications_use_case,
    get_list_pending_overtime_applications_use_case,
    get_overtime_attendance_options_use_case,
    get_recalculate_attendance_range_use_case,
    get_supervisor_team_employees_use_case,
    get_submit_overtime_application_use_case,
    get_update_overtime_application_use_case,
)
from app.attendance.infrastructure.overtime_repository import SqlAlchemyOvertimeRepository
from app.attendance.infrastructure.http_errors import http_errors as _http_errors
from app.attendance.infrastructure.overtime_schemas import (
    OvertimeApplicationDecisionSchema,
    OvertimeApplicationInputSchema,
    OvertimeApplicationSchema,
    OvertimeAttendanceOptionsSchema,
    OvertimeCutoffSchema,
    AttendanceRangeRecalculationInputSchema,
    AttendanceRangeRecalculationSchema,
)
from app.auth.domain.entities.user import Role
from app.auth.infrastructure.dependencies import (
    get_current_authorization_use_case,
    require_any_permission,
    require_permission,
    require_role,
)
from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work

router = APIRouter()


def _user_id(claims: dict) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error


def _application_schema(record: OvertimeApplicationRecord) -> OvertimeApplicationSchema:
    application, employee = record.application, record.employee
    return OvertimeApplicationSchema(
        id=application.id,
        application_no=application.application_no,
        attendance_record_id=record.attendance.id,
        employee_id=employee.id,
        employee_code=employee.employee_no,
        employee_name=employee.display_name,
        attendance_date=application.attendance_date,
        requested_start_at=application.requested_start_at,
        requested_end_at=application.requested_end_at,
        potential_ot_minutes=application.potential_ot_minutes,
        requested_minutes=application.requested_minutes,
        system_validated_minutes=application.system_validated_minutes,
        supervisor_approved_minutes=application.supervisor_approved_minutes,
        final_payable_minutes=application.final_payable_minutes,
        overtime_type=application.overtime_type,
        reason=application.reason,
        work_accomplished=application.work_accomplished,
        validation_status=application.validation_status,
        status=application.status,
        payroll_posted=application.payroll_posted,
    )


def _attendance_item(record: OvertimeAttendance) -> RecentAttendanceItem:
    return RecentAttendanceItem(
        attendance_id=record.id,
        date=record.work_date.isoformat(),
        expected_time_in=record.expected_clock_in_at.isoformat() if record.expected_clock_in_at else None,
        expected_time_out=record.expected_clock_out_at.isoformat() if record.expected_clock_out_at else None,
        time_in=record.effective_clock_in.isoformat(),
        time_out=record.effective_clock_out.isoformat(),
        regular_overtime_minutes=record.regular_overtime_minutes,
        night_differential_overtime_minutes=record.night_differential_overtime_minutes,
        night_differential_minutes=record.night_differential_minutes,
        status="present",
    )


@router.get("/overtime-attendance-options", response_model=ResponseEnvelope[OvertimeAttendanceOptionsSchema])
async def get_overtime_attendance_options(
    claims: dict = Depends(require_permission("overtime.submit_own")),
    use_case: GetOvertimeAttendanceOptionsUseCase = Depends(get_overtime_attendance_options_use_case),
):
    with _http_errors():
        options = await use_case.execute(GetOvertimeAttendanceOptionsInput(user_id=_user_id(claims)))
    return ResponseEnvelope(
        status="success",
        data=OvertimeAttendanceOptionsSchema(
            cutoff=OvertimeCutoffSchema(
                cutoff_code=options.cutoff.cutoff_code,
                period_start=options.cutoff.period_start,
                period_end=options.cutoff.period_end,
            ),
            records=[_attendance_item(record) for record in options.attendance],
        ),
    )


@router.post(
    "/recalculate-range",
    response_model=ResponseEnvelope[list[AttendanceRangeRecalculationSchema]],
    summary="Preview or recalculate attendance for an employee or supervisor team",
)
async def recalculate_attendance_range(
    payload: AttendanceRangeRecalculationInputSchema,
    claims: dict = Depends(
        require_any_permission("attendance.read_own", "attendance.read_team", "attendance.read_org")
    ),
    use_case: RecalculateAttendanceRangeUseCase = Depends(
        get_recalculate_attendance_range_use_case
    ),
    team_use_case: ListSupervisorTeamEmployeesUseCase = Depends(
        get_supervisor_team_employees_use_case
    ),
    authorization_use_case: GetCurrentAuthorizationUseCase = Depends(
        get_current_authorization_use_case
    ),
):
    role_codes = claims.get("role_codes", claims.get("roles", []))
    role_codes = {
        code.strip().upper() for code in role_codes if isinstance(code, str)
    } if isinstance(role_codes, list) else set()
    user_id = _user_id(claims)
    authorization = await authorization_use_case.execute(user_id)

    if payload.scope == "own":
        if "attendance.read_own" not in authorization.permission_codes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
        try:
            employee_ids = [UUID(str(claims["employee_id"]))]
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is not linked to an employee profile.",
            ) from error
    elif payload.scope == "team":
        if "SUPERVISOR" not in role_codes or "attendance.read_team" not in authorization.permission_codes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
        try:
            supervisor_employee_id = UUID(str(claims["employee_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is not linked to an employee profile.",
            ) from error
        team = await team_use_case.execute(
            ListSupervisorTeamEmployeesInput(supervisor_employee_id=supervisor_employee_id)
        )
        employee_ids = [employee.employee_id for employee in team]
        if not employee_ids:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active direct reports found.")
    else:
        if claims.get("role") != Role.ADMIN.value or "attendance.read_org" not in authorization.permission_codes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
        if payload.employee_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Select an employee.")
        employee_ids = [payload.employee_id]

    with _http_errors():
        results = [
            await use_case.execute(
                RecalculateAttendanceRangeInput(
                    actor_user_id=user_id,
                    employee_id=employee_id,
                    from_date=payload.from_date,
                    to_date=payload.to_date,
                    dry_run=payload.dry_run,
                )
            )
            for employee_id in employee_ids
        ]
    return ResponseEnvelope(
        status="success",
        data=[AttendanceRangeRecalculationSchema.model_validate(result) for result in results],
    )


@router.get(
    "/recalculation-default-range",
    response_model=ResponseEnvelope[OvertimeCutoffSchema],
    summary="Get the signed-in employee's current payroll cutoff dates",
)
async def get_recalculation_default_range(
    claims: dict = Depends(require_permission("attendance.read_own")),
    uow: GenUnitOfWork = Depends(get_unit_of_work),
):
    async with uow as active_uow:
        if active_uow.session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        repository = SqlAlchemyOvertimeRepository(active_uow.session)
        employee_id = await repository.get_active_employee_id_for_user(_user_id(claims))
        if employee_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="An active employee linked to your account was not found.",
            )
        cutoff = await repository.get_latest_configured_cutoff(employee_id, ph_today(utc_now()))
        if cutoff is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active payroll cutoff configuration was found for your employee record.",
            )
    return ResponseEnvelope(
        status="success",
        data=OvertimeCutoffSchema(
            cutoff_code=cutoff.cutoff_code,
            period_start=cutoff.period_start,
            period_end=cutoff.period_end,
        ),
    )


@router.post(
    "/overtime-applications/{attendance_id}",
    response_model=ResponseEnvelope[OvertimeApplicationSchema],
    status_code=status.HTTP_201_CREATED,
)
async def submit_overtime_application(
    attendance_id: UUID,
    payload: OvertimeApplicationInputSchema,
    claims: dict = Depends(require_permission("overtime.submit_own")),
    use_case: SubmitOvertimeApplicationUseCase = Depends(get_submit_overtime_application_use_case),
):
    with _http_errors():
        record = await use_case.execute(
            SubmitOvertimeApplicationInput(
                user_id=_user_id(claims),
                attendance_id=attendance_id,
                overtime_type=payload.overtime_type,
                requested_minutes=payload.requested_minutes,
                reason=payload.reason,
                work_accomplished=payload.work_accomplished,
                requested_start_at=payload.requested_start_at,
                requested_end_at=payload.requested_end_at,
            )
        )
    return ResponseEnvelope(status="success", data=_application_schema(record))


@router.put(
    "/overtime-applications/{application_id}",
    response_model=ResponseEnvelope[OvertimeApplicationSchema],
)
async def update_overtime_application(
    application_id: UUID,
    payload: OvertimeApplicationInputSchema,
    claims: dict = Depends(require_permission("overtime.submit_own")),
    use_case: UpdateOvertimeApplicationUseCase = Depends(get_update_overtime_application_use_case),
):
    with _http_errors():
        record = await use_case.execute(
            UpdateOvertimeApplicationInput(
                user_id=_user_id(claims),
                application_id=application_id,
                overtime_type=payload.overtime_type,
                requested_minutes=payload.requested_minutes,
                reason=payload.reason,
                work_accomplished=payload.work_accomplished,
                requested_start_at=payload.requested_start_at,
                requested_end_at=payload.requested_end_at,
            )
        )
    return ResponseEnvelope(status="success", data=_application_schema(record))


@router.get(
    "/overtime-applications",
    response_model=ResponseEnvelope[list[OvertimeApplicationSchema]],
)
async def get_my_overtime_applications(
    claims: dict = Depends(require_permission("overtime.submit_own")),
    use_case: ListMyOvertimeApplicationsUseCase = Depends(get_list_my_overtime_applications_use_case),
):
    records = await use_case.execute(ListMyOvertimeApplicationsInput(user_id=_user_id(claims)))
    return ResponseEnvelope(status="success", data=[_application_schema(record) for record in records])


@router.get(
    "/overtime-applications/pending",
    response_model=ResponseEnvelope[list[OvertimeApplicationSchema]],
)
async def get_pending_overtime_applications(
    claims: dict = Depends(require_permission("overtime.approve_team")),
    use_case: ListPendingOvertimeApplicationsUseCase = Depends(get_list_pending_overtime_applications_use_case),
):
    supervisor_employee_id = None
    if claims.get("role") != Role.ADMIN.value:
        try:
            supervisor_employee_id = UUID(str(claims["employee_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is not linked to a supervisor employee profile.",
            ) from error
    records = await use_case.execute(
        ListPendingOvertimeApplicationsInput(supervisor_employee_id=supervisor_employee_id)
    )
    return ResponseEnvelope(status="success", data=[_application_schema(record) for record in records])


@router.post(
    "/overtime-applications/{application_id}/decision",
    response_model=ResponseEnvelope[OvertimeApplicationSchema],
)
async def decide_overtime_application(
    application_id: UUID,
    payload: OvertimeApplicationDecisionSchema,
    claims: dict = Depends(require_permission("overtime.approve_team")),
    use_case: DecideOvertimeApplicationUseCase = Depends(get_decide_overtime_application_use_case),
):
    is_admin = claims.get("role") == Role.ADMIN.value
    try:
        actor_id = UUID(str(claims["sub"]))
        actor_employee_id = (
            UUID(str(claims["employee_id"])) if claims.get("employee_id") is not None else None
        )
        if not is_admin and actor_employee_id is None:
            raise ValueError("Supervisor employee id is missing.")
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to a supervisor employee profile.",
        ) from error

    with _http_errors():
        record = await use_case.execute(
            DecideOvertimeApplicationInput(
                application_id=application_id,
                actor_id=actor_id,
                actor_employee_id=actor_employee_id,
                is_admin=is_admin,
                decision=payload.decision,
                supervisor_approved_minutes=payload.supervisor_approved_minutes,
            )
        )
    return ResponseEnvelope(status="success", data=_application_schema(record))
