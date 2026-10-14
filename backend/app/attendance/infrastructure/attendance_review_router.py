from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.attendance.application.attendance_review_use_cases import (
    ApproveInvalidAttendanceInput,
    ApproveInvalidAttendanceUseCase,
    ListInvalidAttendanceInput,
    ListInvalidAttendanceUseCase,
)
from app.attendance.domain.entities.attendance_review import ReviewableAttendanceRecord
from app.attendance.infrastructure.dependencies import (
    get_approve_invalid_attendance_use_case,
    get_list_invalid_attendance_use_case,
)
from app.attendance.infrastructure.http_errors import http_errors
from app.auth.domain.entities.user import Role
from app.auth.infrastructure.dependencies import require_permission
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
    claims: dict = Depends(require_permission("attendance.read_team")),
    use_case: ListInvalidAttendanceUseCase = Depends(get_list_invalid_attendance_use_case),
):
    supervisor_employee_id = None
    if claims.get("role") != Role.ADMIN.value:
        try:
            supervisor_employee_id = UUID(str(claims["employee_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_LINKED_TO_EMPLOYEE) from error
    records = await use_case.execute(ListInvalidAttendanceInput(supervisor_employee_id=supervisor_employee_id))
    return ResponseEnvelope(status="success", data=[_schema(record) for record in records])


@router.post(
    "/supervisor/invalid-attendance/{attendance_id}/approve",
    response_model=ResponseEnvelope[SupervisorInvalidAttendanceSchema],
)
async def approve_supervisor_invalid_attendance(
    attendance_id: UUID,
    claims: dict = Depends(require_permission("attendance.read_team")),
    use_case: ApproveInvalidAttendanceUseCase = Depends(get_approve_invalid_attendance_use_case),
):
    is_admin = claims.get("role") == Role.ADMIN.value
    try:
        actor_id = UUID(str(claims["sub"]))
        supervisor_employee_id = None if is_admin else UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_LINKED_TO_EMPLOYEE) from error

    with http_errors():
        record = await use_case.execute(
            ApproveInvalidAttendanceInput(
                attendance_id=attendance_id,
                actor_id=actor_id,
                supervisor_employee_id=supervisor_employee_id,
            )
        )
    return ResponseEnvelope(status="success", data=_schema(record))
