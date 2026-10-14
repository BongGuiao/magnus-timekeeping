from datetime import date
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.schedule.application.employee_schedule_assignment_use_case import (
    ApproveEmployeeScheduleAssignmentUseCase,
    CreateEmployeeScheduleAssignmentUseCase,
    DeactivateEmployeeScheduleAssignmentUseCase,
    EmployeeScheduleAssignmentConflictError,
    EmployeeScheduleAssignmentReferenceError,
    EmployeeScheduleAssignmentValidationError,
    GetEmployeeScheduleAssignmentUseCase,
    ListEmployeeScheduleAssignmentsUseCase,
    UpdateEmployeeScheduleAssignmentUseCase,
)
from app.filemaintenance.schedule.domain.entities.employee_schedule_assignment import (
    EmployeeScheduleAssignmentEntity,
)
from app.filemaintenance.schedule.infrastructure.dependencies import (
    get_approve_employee_schedule_assignment_use_case,
    get_create_employee_schedule_assignment_use_case,
    get_deactivate_employee_schedule_assignment_use_case,
    get_employee_schedule_assignment_use_case,
    get_list_employee_schedule_assignments_use_case,
    get_update_employee_schedule_assignment_use_case,
)

router = APIRouter(
    prefix="/employee-schedule-assignments",
    tags=["Employee Schedule Assignments"],
    dependencies=[Depends(require_permission("schedule.manage"))],
)


class CreateEmployeeScheduleAssignmentSchema(BaseModel):
    employee_id: UUID
    schedule_template_id: UUID
    rest_day_pattern_id: UUID | None = None
    assignment_type: str = Field(min_length=1, max_length=30)
    effective_from: date
    effective_to: date | None = None
    reason: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_assignment(self) -> "CreateEmployeeScheduleAssignmentSchema":
        self.assignment_type = self.assignment_type.strip()
        if not self.assignment_type:
            raise ValueError("assignment_type cannot be blank.")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from.")
        if self.reason is not None:
            self.reason = self.reason.strip() or None
        return self


class UpdateEmployeeScheduleAssignmentSchema(BaseModel):
    employee_id: UUID | None = None
    schedule_template_id: UUID | None = None
    rest_day_pattern_id: UUID | None = None
    assignment_type: str | None = Field(default=None, min_length=1, max_length=30)
    effective_from: date | None = None
    effective_to: date | None = None
    reason: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "UpdateEmployeeScheduleAssignmentSchema":
        nullable_fields = {"rest_day_pattern_id", "effective_to", "reason"}
        for field_name in self.model_fields_set - nullable_fields:
            value = getattr(self, field_name)
            if value is None:
                raise ValueError(f"{field_name} cannot be null.")
            if field_name == "assignment_type":
                value = value.strip()
                if not value:
                    raise ValueError("assignment_type cannot be blank.")
                setattr(self, field_name, value)
        if "reason" in self.model_fields_set and self.reason is not None:
            self.reason = self.reason.strip() or None
        return self


def _actor_id(claims: dict[str, Any]) -> UUID:
    if not claims.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token.",
        )
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error


def _require_admin(claims: dict[str, Any]) -> None:
    if claims.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role is required to manage employee schedule assignments.",
        )


def _raise_assignment_error(error: ValueError) -> None:
    if isinstance(error, EmployeeScheduleAssignmentConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if isinstance(
        error,
        (
            EmployeeScheduleAssignmentReferenceError,
            EmployeeScheduleAssignmentValidationError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    raise error


@router.post(
    "/create",
    response_model=ResponseEnvelope[EmployeeScheduleAssignmentEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_employee_schedule_assignment(
    payload: CreateEmployeeScheduleAssignmentSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateEmployeeScheduleAssignmentUseCase = Depends(
        get_create_employee_schedule_assignment_use_case
    ),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    values = stamp_audit_fields(payload.model_dump(mode="python"), actor_id, creating=True)
    try:
        result = await use_case.execute(values)
    except (
        EmployeeScheduleAssignmentConflictError,
        EmployeeScheduleAssignmentReferenceError,
        EmployeeScheduleAssignmentValidationError,
    ) as error:
        _raise_assignment_error(error)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="employee_schedule_assignment",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[EmployeeScheduleAssignmentEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_employee_schedule_assignments(
    employee_id: UUID | None = None,
    schedule_template_id: UUID | None = None,
    rest_day_pattern_id: UUID | None = None,
    assignment_status: str | None = None,
    is_active: bool | None = None,
    effective_on: date | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListEmployeeScheduleAssignmentsUseCase = Depends(
        get_list_employee_schedule_assignments_use_case
    ),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(
        employee_id,
        schedule_template_id,
        rest_day_pattern_id,
        assignment_status,
        is_active,
        effective_on,
        offset,
        limit,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{assignment_id}",
    response_model=ResponseEnvelope[EmployeeScheduleAssignmentEntity],
    status_code=status.HTTP_200_OK,
)
async def get_employee_schedule_assignment(
    assignment_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetEmployeeScheduleAssignmentUseCase = Depends(
        get_employee_schedule_assignment_use_case
    ),
):
    _actor_id(claims)
    _require_admin(claims)
    result = await use_case.execute(assignment_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee schedule assignment not found.",
        )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/{assignment_id}",
    response_model=ResponseEnvelope[EmployeeScheduleAssignmentEntity],
    status_code=status.HTTP_200_OK,
)
async def update_employee_schedule_assignment(
    assignment_id: UUID,
    payload: UpdateEmployeeScheduleAssignmentSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateEmployeeScheduleAssignmentUseCase = Depends(
        get_update_employee_schedule_assignment_use_case
    ),
    get_use_case: GetEmployeeScheduleAssignmentUseCase = Depends(
        get_employee_schedule_assignment_use_case
    ),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    before = await get_use_case.execute(assignment_id)
    if before is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee schedule assignment not found.",
        )
    values = payload.model_dump(mode="python", exclude_unset=True)
    stamp_audit_fields(values, actor_id, creating=False)
    try:
        result = await use_case.execute(assignment_id, values)
    except (
        EmployeeScheduleAssignmentConflictError,
        EmployeeScheduleAssignmentReferenceError,
        EmployeeScheduleAssignmentValidationError,
    ) as error:
        _raise_assignment_error(error)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee schedule assignment not found.",
        )
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="employee_schedule_assignment",
        resource_id=assignment_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/{assignment_id}/approve",
    response_model=ResponseEnvelope[EmployeeScheduleAssignmentEntity],
    status_code=status.HTTP_200_OK,
)
async def approve_employee_schedule_assignment(
    assignment_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ApproveEmployeeScheduleAssignmentUseCase = Depends(
        get_approve_employee_schedule_assignment_use_case
    ),
    get_use_case: GetEmployeeScheduleAssignmentUseCase = Depends(
        get_employee_schedule_assignment_use_case
    ),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    before = await get_use_case.execute(assignment_id)
    if before is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee schedule assignment not found.",
        )
    try:
        result = await use_case.execute(assignment_id, actor_id)
    except EmployeeScheduleAssignmentConflictError as error:
        _raise_assignment_error(error)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee schedule assignment not found.",
        )
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="APPROVE",
        resource="employee_schedule_assignment",
        resource_id=assignment_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/{assignment_id}",
    response_model=ResponseEnvelope[EmployeeScheduleAssignmentEntity],
    status_code=status.HTTP_200_OK,
)
async def deactivate_employee_schedule_assignment(
    assignment_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: DeactivateEmployeeScheduleAssignmentUseCase = Depends(
        get_deactivate_employee_schedule_assignment_use_case
    ),
    get_use_case: GetEmployeeScheduleAssignmentUseCase = Depends(
        get_employee_schedule_assignment_use_case
    ),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _actor_id(claims)
    _require_admin(claims)
    before = await get_use_case.execute(assignment_id)
    if before is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee schedule assignment not found.",
        )
    result = await use_case.execute(assignment_id, actor_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee schedule assignment not found.",
        )
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="employee_schedule_assignment",
        resource_id=assignment_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)
