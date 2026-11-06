from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.attendance.application.attendance_review_use_cases import (
    ApproveInvalidAttendanceInput,
    ApproveInvalidAttendanceUseCase,
    ListInvalidAttendanceInput,
    ListInvalidAttendanceUseCase,
    ListUnresolvedAttendanceRoutesUseCase,
    RetryUnresolvedAttendanceRouteUseCase,
)
from app.attendance.domain.entities.attendance_review import ReviewableAttendanceRecord
from app.attendance.infrastructure.dependencies import (
    get_approve_invalid_attendance_use_case,
    get_list_invalid_attendance_use_case,
    get_list_unresolved_attendance_routes_use_case,
    get_retry_unresolved_attendance_route_use_case,
)
from app.attendance.infrastructure.http_errors import http_errors
from app.auth.domain.entities.user import Role
from app.auth.infrastructure.approval_scope import approval_supervisor_scope, has_supervisor_role
from app.auth.infrastructure.dependencies import require_approval_permission, require_permission
from app.core.generics.mapper import ResponseEnvelope

router = APIRouter()

NOT_LINKED_TO_EMPLOYEE = "This account is not linked to an employee profile."


class SupervisorInvalidAttendanceSchema(BaseModel):
    id: UUID
    employee_id: UUID
    employee_code: str
    employee_name: str
    work_date: date
    time_in: datetime | None
    time_out: datetime | None


class UnresolvedAttendanceRouteSchema(SupervisorInvalidAttendanceSchema):
    routing_error: str


def _actor_employee_id(claims: dict) -> UUID | None:
    employee_id = claims.get("employee_id")
    if employee_id is None:
        return None
    try:
        return UUID(str(employee_id))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_LINKED_TO_EMPLOYEE) from error


def _schema(record: ReviewableAttendanceRecord) -> SupervisorInvalidAttendanceSchema:
    attendance, employee = record.attendance, record.employee
    return SupervisorInvalidAttendanceSchema(
        id=attendance.id,
        employee_id=employee.id,
        employee_code=employee.employee_no,
        employee_name=employee.display_name,
        work_date=attendance.work_date,
        time_in=attendance.effective_clock_in,
        time_out=attendance.effective_clock_out,
    )


@router.get(
    "/supervisor/invalid-attendance",
    response_model=ResponseEnvelope[list[SupervisorInvalidAttendanceSchema]],
)
async def get_supervisor_invalid_attendance(
    claims: dict = Depends(require_approval_permission("attendance.read_team")),
    use_case: ListInvalidAttendanceUseCase = Depends(get_list_invalid_attendance_use_case),
):
    is_admin = claims.get("role") == Role.ADMIN.value and not has_supervisor_role(claims)
    supervisor_employee_id = approval_supervisor_scope(
        claims,
        is_admin=is_admin,
        detail=NOT_LINKED_TO_EMPLOYEE,
    )
    records = await use_case.execute(ListInvalidAttendanceInput(
        supervisor_employee_id=supervisor_employee_id, actor_employee_id=_actor_employee_id(claims),
    ))
    return ResponseEnvelope(status="success", data=[_schema(record) for record in records])


@router.post(
    "/supervisor/invalid-attendance/{attendance_id}/approve",
    response_model=ResponseEnvelope[SupervisorInvalidAttendanceSchema],
)
async def approve_supervisor_invalid_attendance(
    attendance_id: UUID,
    claims: dict = Depends(require_approval_permission("attendance.read_team")),
    use_case: ApproveInvalidAttendanceUseCase = Depends(get_approve_invalid_attendance_use_case),
):
    is_admin = claims.get("role") == Role.ADMIN.value and not has_supervisor_role(claims)
    try:
        actor_id = UUID(str(claims["sub"]))
        supervisor_employee_id = approval_supervisor_scope(
            claims,
            is_admin=is_admin,
            detail=NOT_LINKED_TO_EMPLOYEE,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_LINKED_TO_EMPLOYEE) from error

    with http_errors():
        record = await use_case.execute(
            ApproveInvalidAttendanceInput(
                attendance_id=attendance_id,
                actor_id=actor_id,
                supervisor_employee_id=supervisor_employee_id,
                actor_employee_id=_actor_employee_id(claims),
            )
        )
    return ResponseEnvelope(status="success", data=_schema(record))


@router.get(
    "/hr/unresolved-attendance-approvals",
    response_model=ResponseEnvelope[list[UnresolvedAttendanceRouteSchema]],
)
async def list_unresolved_attendance_approvals(
    _claims: dict = Depends(require_permission("employees.manage")),
    use_case: ListUnresolvedAttendanceRoutesUseCase = Depends(get_list_unresolved_attendance_routes_use_case),
):
    records = await use_case.execute()
    return ResponseEnvelope(status="success", data=[
        UnresolvedAttendanceRouteSchema(
            **_schema(item.record).model_dump(), routing_error=item.routing_error,
        )
        for item in records
    ])


@router.post(
    "/hr/unresolved-attendance-approvals/{attendance_id}/retry",
    response_model=ResponseEnvelope[bool],
)
async def retry_unresolved_attendance_approval(
    attendance_id: UUID,
    claims: dict = Depends(require_permission("employees.manage")),
    use_case: RetryUnresolvedAttendanceRouteUseCase = Depends(get_retry_unresolved_attendance_route_use_case),
):
    try:
        actor_id = UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid user identity.") from error
    with http_errors():
        await use_case.execute(attendance_id, actor_id)
    return ResponseEnvelope(status="success", data=True)
