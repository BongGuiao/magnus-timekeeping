from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth.infrastructure.dependencies import require_permission
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.schedule.application.emergency_schedule_use_cases import (
    EmergencyScheduleRequestView,
    EmergencyScheduleTemplateOption,
    EmergencyScheduleTemplatesInput,
    ListEmergencyScheduleRequestsInput,
    ListPendingEmergencyScheduleRequestsInput,
    ReviewEmergencyScheduleRequestInput,
    SubmitEmergencyScheduleRequestInput,
)
from app.filemaintenance.schedule.domain.schedule_upload_rules import MAX_REASON_LENGTH
from app.filemaintenance.schedule.infrastructure.emergency_schedule_dependencies import (
    get_list_emergency_schedule_templates_use_case,
    get_list_my_emergency_schedule_requests_use_case,
    get_list_pending_emergency_schedule_requests_use_case,
    get_review_emergency_schedule_request_use_case,
    get_submit_emergency_schedule_request_use_case,
)
from app.filemaintenance.schedule.application.emergency_schedule_use_cases import (
    ListEmergencyScheduleTemplatesUseCase,
    ListMyEmergencyScheduleRequestsUseCase,
    ListPendingEmergencyScheduleRequestsUseCase,
    ReviewEmergencyScheduleRequestUseCase,
    SubmitEmergencyScheduleRequestUseCase,
)

router = APIRouter(prefix="/emergency-schedule-requests", tags=["Emergency Schedule Requests"])


class EmergencyScheduleTemplateOptionSchema(BaseModel):
    id: UUID
    schedule_code: str
    schedule_name: str
    schedule_type: str


class EmergencyScheduleRequestSchema(BaseModel):
    id: UUID
    employee_code: str
    employee_name: str
    schedule_code: str
    schedule_name: str
    work_date: date
    reason: str
    status: str
    requested_at: datetime
    reviewed_at: datetime | None
    review_remarks: str | None


class EmergencyScheduleRequestCreateSchema(BaseModel):
    schedule_template_id: UUID
    work_date: date
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class EmergencyScheduleReviewSchema(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    remarks: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)


def _user_id(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error


def _employee_id(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["employee_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not linked to an employee profile.",
        ) from error


def _request_schema(view: EmergencyScheduleRequestView) -> EmergencyScheduleRequestSchema:
    return EmergencyScheduleRequestSchema(
        id=view.id,
        employee_code=view.employee_code,
        employee_name=view.employee_name,
        schedule_code=view.schedule_code,
        schedule_name=view.schedule_name,
        work_date=view.work_date,
        reason=view.reason,
        status=view.status,
        requested_at=view.requested_at,
        reviewed_at=view.reviewed_at,
        review_remarks=view.review_remarks,
    )


def _template_schema(
    template: EmergencyScheduleTemplateOption,
) -> EmergencyScheduleTemplateOptionSchema:
    return EmergencyScheduleTemplateOptionSchema(
        id=template.id,
        schedule_code=template.schedule_code,
        schedule_name=template.schedule_name,
        schedule_type=template.schedule_type,
    )


def _validation_error(error: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


@router.get("/templates", response_model=ResponseEnvelope[list[EmergencyScheduleTemplateOptionSchema]])
async def list_emergency_schedule_templates(
    work_date: date = Query(...),
    claims: dict[str, Any] = Depends(require_permission("schedule.request_emergency")),
    use_case: ListEmergencyScheduleTemplatesUseCase = Depends(
        get_list_emergency_schedule_templates_use_case
    ),
):
    try:
        templates = await use_case.execute(
            EmergencyScheduleTemplatesInput(employee_id=_employee_id(claims), work_date=work_date)
        )
    except ValueError as error:
        raise _validation_error(error) from error
    return ResponseEnvelope(
        status="success",
        data=[_template_schema(template) for template in templates],
    )


@router.get("", response_model=ResponseEnvelope[list[EmergencyScheduleRequestSchema]])
async def list_my_emergency_schedule_requests(
    claims: dict[str, Any] = Depends(require_permission("schedule.request_emergency")),
    use_case: ListMyEmergencyScheduleRequestsUseCase = Depends(
        get_list_my_emergency_schedule_requests_use_case
    ),
):
    requests = await use_case.execute(
        ListEmergencyScheduleRequestsInput(employee_id=_employee_id(claims))
    )
    return ResponseEnvelope(
        status="success",
        data=[_request_schema(request) for request in requests],
    )


@router.post(
    "",
    response_model=ResponseEnvelope[EmergencyScheduleRequestSchema],
    status_code=status.HTTP_201_CREATED,
)
async def submit_emergency_schedule_request(
    payload: EmergencyScheduleRequestCreateSchema,
    claims: dict[str, Any] = Depends(require_permission("schedule.request_emergency")),
    use_case: SubmitEmergencyScheduleRequestUseCase = Depends(
        get_submit_emergency_schedule_request_use_case
    ),
):
    try:
        request = await use_case.execute(
            SubmitEmergencyScheduleRequestInput(
                employee_id=_employee_id(claims),
                user_id=_user_id(claims),
                schedule_template_id=payload.schedule_template_id,
                work_date=payload.work_date,
                reason=payload.reason,
            )
        )
    except ValueError as error:
        raise _validation_error(error) from error
    return ResponseEnvelope(status="success", data=_request_schema(request))


@router.get("/pending", response_model=ResponseEnvelope[list[EmergencyScheduleRequestSchema]])
async def list_pending_emergency_schedule_requests(
    claims: dict[str, Any] = Depends(require_permission("schedule.approve_emergency")),
    use_case: ListPendingEmergencyScheduleRequestsUseCase = Depends(
        get_list_pending_emergency_schedule_requests_use_case
    ),
):
    requests = await use_case.execute(
        ListPendingEmergencyScheduleRequestsInput(
            supervisor_employee_id=_employee_id(claims)
        )
    )
    return ResponseEnvelope(
        status="success",
        data=[_request_schema(request) for request in requests],
    )


@router.post(
    "/{request_id}/review",
    response_model=ResponseEnvelope[EmergencyScheduleRequestSchema],
)
async def review_emergency_schedule_request(
    request_id: UUID,
    payload: EmergencyScheduleReviewSchema,
    claims: dict[str, Any] = Depends(require_permission("schedule.approve_emergency")),
    use_case: ReviewEmergencyScheduleRequestUseCase = Depends(
        get_review_emergency_schedule_request_use_case
    ),
):
    try:
        request = await use_case.execute(
            ReviewEmergencyScheduleRequestInput(
                request_id=request_id,
                supervisor_employee_id=_employee_id(claims),
                reviewer_user_id=_user_id(claims),
                decision=payload.decision,
                remarks=payload.remarks,
            )
        )
    except ValueError as error:
        raise _validation_error(error) from error
    return ResponseEnvelope(status="success", data=_request_schema(request))
