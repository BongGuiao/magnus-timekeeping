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
    SubmitOvertimeApplicationInput,
    SubmitOvertimeApplicationUseCase,
)
from app.attendance.application.recent_attendance_snapshot import RecentAttendanceItem
from app.attendance.domain.entities.overtime import OvertimeApplicationRecord, OvertimeAttendance
from app.attendance.infrastructure.dependencies import (
    get_decide_overtime_application_use_case,
    get_list_my_overtime_applications_use_case,
    get_list_pending_overtime_applications_use_case,
    get_overtime_attendance_options_use_case,
    get_submit_overtime_application_use_case,
)
from app.attendance.infrastructure.http_errors import http_errors as _http_errors
from app.attendance.infrastructure.overtime_schemas import (
    OvertimeApplicationDecisionSchema,
    OvertimeApplicationInputSchema,
    OvertimeApplicationSchema,
    OvertimeAttendanceOptionsSchema,
    OvertimeCutoffSchema,
)
from app.auth.domain.entities.user import Role
from app.auth.infrastructure.dependencies import require_permission
from app.core.generics.mapper import ResponseEnvelope

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
