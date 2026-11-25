from datetime import date, datetime
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.application.authorization import CurrentAuthorization, GetCurrentAuthorizationUseCase
from app.auth.infrastructure.dependencies import (
    get_current_authorization_use_case, get_current_user_claims, require_any_permission, require_permission,
)
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.employees.application.related_use_case import ListEmploymentAssignmentsUseCase
from app.filemaintenance.employees.application.use_case import GetEmployeeUseCase
from app.filemaintenance.employees.infrastructure.dependencies import (
    get_employee_use_case, get_list_assignments_use_case,
)
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
from app.filemaintenance.schedule.application.rest_day_pattern_use_case import ListRestDayPatternsUseCase
from app.filemaintenance.schedule.application.use_case import ListScheduleTemplatesUseCase
from app.filemaintenance.schedule.domain.entities.employee_schedule_assignment import (
    EmployeeScheduleAssignmentEntity,
)
from app.filemaintenance.schedule.domain.entities.rest_day_pattern import RestDayPatternEntity
from app.filemaintenance.schedule.domain.entities.schedule_template import ScheduleTemplateEntity
from app.filemaintenance.schedule.infrastructure.dependencies import (
    get_approve_employee_schedule_assignment_use_case,
    get_create_employee_schedule_assignment_use_case,
    get_deactivate_employee_schedule_assignment_use_case,
    get_employee_schedule_assignment_use_case,
    get_list_employee_schedule_assignments_use_case,
    get_list_rest_day_patterns_use_case,
    get_list_schedule_templates_use_case,
    get_update_employee_schedule_assignment_use_case,
)

router = APIRouter(
    prefix="/employee-schedule-assignments",
    tags=["Employee Schedule Assignments"],
    dependencies=[Depends(require_any_permission("schedule.manage", "schedule.manage_team"))],
)


class TeamScheduleOptions(BaseModel):
    has_current_assignment: bool
    templates: list[ScheduleTemplateEntity]
    patterns: list[RestDayPatternEntity]


async def _schedule_authorization(
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetCurrentAuthorizationUseCase = Depends(get_current_authorization_use_case),
) -> CurrentAuthorization:
    return await use_case.execute(_actor_id(claims))


async def _require_employee_scope(
    employee_id: UUID,
    claims: dict[str, Any],
    authorization: CurrentAuthorization,
    employees: GetEmployeeUseCase,
) -> bool:
    if "schedule.manage" in authorization.permission_codes and claims.get("role") == "admin":
        return False
    if (
        "schedule.manage_team" not in authorization.permission_codes
        or authorization.employee_id is None
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
    if await employees.execute(employee_id, authorization.employee_id) is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Employee is not a current direct report.")
    return True


async def _team_options(
    employee_id: UUID,
    employment: ListEmploymentAssignmentsUseCase,
    assignments: ListEmployeeScheduleAssignmentsUseCase,
    templates: ListScheduleTemplatesUseCase,
    patterns: ListRestDayPatternsUseCase,
) -> TeamScheduleOptions:
    today = datetime.now(ZoneInfo("Asia/Manila")).date()
    employment_rows = await employment.execute(employee_id)
    current = next((row for row in employment_rows if row.is_active and row.status == "ACTIVE"
                    and row.effective_from <= today
                    and (row.effective_to is None or row.effective_to >= today)
                    and (row.separation_date is None or row.separation_date >= today)), None)
    if current is None:
        return TeamScheduleOptions(has_current_assignment=False, templates=[], patterns=[])
    existing = await assignments.execute(employee_id)
    assigned_template_ids = {row.schedule_template_id for row in existing}
    assigned_pattern_ids = {row.rest_day_pattern_id for row in existing if row.rest_day_pattern_id}
    all_templates = await templates.execute(company_id=current.company_id, limit=1000)
    allowed_templates = [row for row in all_templates
                         if (row.is_active and row.status == "ACTIVE") or row.id in assigned_template_ids]
    template_ids = {row.id for row in allowed_templates}
    all_patterns = await patterns.execute(True)
    allowed_patterns = [row for row in all_patterns if row.id in assigned_pattern_ids
                        or all(day.schedule_template_id is None or day.schedule_template_id in template_ids
                               for day in row.days)]
    return TeamScheduleOptions(
        has_current_assignment=True, templates=allowed_templates, patterns=allowed_patterns,
    )


@dataclass
class TeamOptionsDependencies:
    employment: ListEmploymentAssignmentsUseCase
    assignments: ListEmployeeScheduleAssignmentsUseCase
    templates: ListScheduleTemplatesUseCase
    patterns: ListRestDayPatternsUseCase

    async def get(self, employee_id: UUID) -> TeamScheduleOptions:
        return await _team_options(
            employee_id, self.employment, self.assignments, self.templates, self.patterns,
        )


def _options_dependencies(
    employment: ListEmploymentAssignmentsUseCase = Depends(get_list_assignments_use_case),
    assignments: ListEmployeeScheduleAssignmentsUseCase = Depends(get_list_employee_schedule_assignments_use_case),
    templates: ListScheduleTemplatesUseCase = Depends(get_list_schedule_templates_use_case),
    patterns: ListRestDayPatternsUseCase = Depends(get_list_rest_day_patterns_use_case),
) -> TeamOptionsDependencies:
    return TeamOptionsDependencies(employment, assignments, templates, patterns)


async def _validate_team_options(
    employee_id: UUID,
    template_id: UUID | None,
    pattern_id: UUID | None,
    options: TeamOptionsDependencies,
) -> None:
    available = await options.get(employee_id)
    if not available.has_current_assignment:
        raise HTTPException(status_code=422, detail="No active employment assignment was found.")
    if template_id is not None and template_id not in {item.id for item in available.templates}:
        raise HTTPException(status_code=422, detail="Schedule template is not available for this employee.")
    if pattern_id is not None and pattern_id not in {item.id for item in available.patterns}:
        raise HTTPException(status_code=422, detail="Rest-day pattern is not available for this employee.")


class CreateEmployeeScheduleAssignmentSchema(BaseModel):
    employee_id: UUID
    schedule_template_id: UUID
    rest_day_pattern_id: UUID | None = None
    assignment_type: str = Field(min_length=1, max_length=30)
    attendance_mode: Literal["PUNCH_REQUIRED", "SCHEDULE_CREDITED"] = "PUNCH_REQUIRED"
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
    attendance_mode: Literal["PUNCH_REQUIRED", "SCHEDULE_CREDITED"] | None = None
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
    authorization: CurrentAuthorization = Depends(_schedule_authorization),
    employees: GetEmployeeUseCase = Depends(get_employee_use_case),
    options: TeamOptionsDependencies = Depends(_options_dependencies),
):
    actor_id = _actor_id(claims)
    team = await _require_employee_scope(payload.employee_id, claims, authorization, employees)
    if team:
        await _validate_team_options(payload.employee_id, payload.schedule_template_id, payload.rest_day_pattern_id, options)
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
    authorization: CurrentAuthorization = Depends(_schedule_authorization),
    employees: GetEmployeeUseCase = Depends(get_employee_use_case),
):
    _actor_id(claims)
    if employee_id is None:
        _require_admin(claims)
        if "schedule.manage" not in authorization.permission_codes:
            raise HTTPException(status_code=403, detail="Permission denied.")
    else:
        await _require_employee_scope(employee_id, claims, authorization, employees)
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


@router.get("/team-options/{employee_id}", response_model=ResponseEnvelope[TeamScheduleOptions])
async def get_team_schedule_options(
    employee_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    authorization: CurrentAuthorization = Depends(_schedule_authorization),
    employees: GetEmployeeUseCase = Depends(get_employee_use_case),
    options: TeamOptionsDependencies = Depends(_options_dependencies),
):
    await _require_employee_scope(employee_id, claims, authorization, employees)
    return ResponseEnvelope(status="success", data=await options.get(employee_id))


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
    authorization: CurrentAuthorization = Depends(_schedule_authorization),
    employees: GetEmployeeUseCase = Depends(get_employee_use_case),
):
    _actor_id(claims)
    result = await use_case.execute(assignment_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee schedule assignment not found.",
        )
    await _require_employee_scope(result.employee_id, claims, authorization, employees)
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
    authorization: CurrentAuthorization = Depends(_schedule_authorization),
    employees: GetEmployeeUseCase = Depends(get_employee_use_case),
    options: TeamOptionsDependencies = Depends(_options_dependencies),
):
    actor_id = _actor_id(claims)
    before = await get_use_case.execute(assignment_id)
    if before is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee schedule assignment not found.",
        )
    team = await _require_employee_scope(before.employee_id, claims, authorization, employees)
    if team:
        if payload.employee_id is not None and payload.employee_id != before.employee_id:
            raise HTTPException(status_code=403, detail="Cannot transfer a schedule assignment.")
        await _validate_team_options(before.employee_id, payload.schedule_template_id, payload.rest_day_pattern_id, options)
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
    dependencies=[Depends(require_permission("schedule.manage"))],
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
    authorization: CurrentAuthorization = Depends(_schedule_authorization),
    employees: GetEmployeeUseCase = Depends(get_employee_use_case),
):
    actor_id = _actor_id(claims)
    before = await get_use_case.execute(assignment_id)
    if before is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee schedule assignment not found.",
        )
    await _require_employee_scope(before.employee_id, claims, authorization, employees)
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
