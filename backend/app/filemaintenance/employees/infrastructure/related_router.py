from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from elasticsearch import AsyncElasticsearch

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.employees.application.related_use_case import (
    CreateEmployeeSkillUseCase,
    CreateEmploymentAssignmentUseCase,
    GetEmployeeSkillUseCase,
    GetEmploymentAssignmentUseCase,
    ListEmployeeSkillsUseCase,
    ListEmploymentAssignmentsUseCase,
    UpdateEmployeeSkillUseCase,
    UpdateEmploymentAssignmentUseCase,
)
from app.filemaintenance.employees.domain.entities.employee_skill import EmployeeSkillEntity
from app.filemaintenance.employees.domain.entities.employment_assignment import EmploymentAssignmentEntity
from app.filemaintenance.employees.infrastructure.dependencies import (
    get_assignment_use_case,
    get_create_assignment_use_case,
    get_create_skill_use_case,
    get_list_assignments_use_case,
    get_list_skills_use_case,
    get_skill_use_case,
    get_update_assignment_use_case,
    get_update_skill_use_case,
)
from app.filemaintenance.employees.infrastructure.router import _get_user_id, _require_email

assignments_router = APIRouter(prefix="/employment-assignments", tags=["Employment Assignments"])
skills_router = APIRouter(prefix="/employee-skills", tags=["Employee Skills"])


def _pop_record_id(payload: dict[str, Any], label: str) -> UUID:
    record_id = payload.pop("id", None)
    if not record_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{label} id is required.")
    try:
        return UUID(str(record_id))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} id must be a UUID.",
        ) from error


@assignments_router.post(
    "/create",
    response_model=ResponseEnvelope[EmploymentAssignmentEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateEmploymentAssignmentUseCase = Depends(get_create_assignment_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    result = await use_case.execute(stamp_audit_fields(payload, user_id, creating=True))
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="CREATE",
        resource="employment_assignment",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@assignments_router.put(
    "/update",
    response_model=ResponseEnvelope[EmploymentAssignmentEntity],
    status_code=status.HTTP_200_OK,
)
async def update_assignment(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateEmploymentAssignmentUseCase = Depends(get_update_assignment_use_case),
    get_use_case: GetEmploymentAssignmentUseCase = Depends(get_assignment_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    assignment_id = _pop_record_id(payload, "Employment assignment")
    user_id = _get_user_id(claims)
    stamp_audit_fields(payload, user_id, creating=False)
    before = await get_use_case.execute(assignment_id)
    result = await use_case.execute(assignment_id, payload)
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="UPDATE",
        resource="employment_assignment",
        resource_id=assignment_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@assignments_router.get(
    "/list",
    response_model=ResponseEnvelope[list[EmploymentAssignmentEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_assignments(
    employee_id: UUID | None = None,
    company_id: UUID | None = None,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListEmploymentAssignmentsUseCase = Depends(get_list_assignments_use_case),
):
    _require_email(claims)
    result = await use_case.execute(employee_id, company_id)
    return ResponseEnvelope(status="success", data=result)


@assignments_router.get(
    "/{assignment_id}",
    response_model=ResponseEnvelope[EmploymentAssignmentEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_assignment(
    assignment_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetEmploymentAssignmentUseCase = Depends(get_assignment_use_case),
):
    _require_email(claims)
    result = await use_case.execute(assignment_id)
    return ResponseEnvelope(status="success", data=result)


@skills_router.post(
    "/create",
    response_model=ResponseEnvelope[EmployeeSkillEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_skill(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateEmployeeSkillUseCase = Depends(get_create_skill_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    result = await use_case.execute(stamp_audit_fields(payload, user_id, creating=True))
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="CREATE",
        resource="employee_skill",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@skills_router.put(
    "/update",
    response_model=ResponseEnvelope[EmployeeSkillEntity],
    status_code=status.HTTP_200_OK,
)
async def update_skill(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateEmployeeSkillUseCase = Depends(get_update_skill_use_case),
    get_use_case: GetEmployeeSkillUseCase = Depends(get_skill_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    skill_id = _pop_record_id(payload, "Employee skill")
    user_id = _get_user_id(claims)
    stamp_audit_fields(payload, user_id, creating=False)
    before = await get_use_case.execute(skill_id)
    result = await use_case.execute(skill_id, payload)
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="UPDATE",
        resource="employee_skill",
        resource_id=skill_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@skills_router.get(
    "/list",
    response_model=ResponseEnvelope[list[EmployeeSkillEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_skills(
    employee_id: UUID | None = None,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListEmployeeSkillsUseCase = Depends(get_list_skills_use_case),
):
    _require_email(claims)
    result = await use_case.execute(employee_id)
    return ResponseEnvelope(status="success", data=result)


@skills_router.get(
    "/{skill_id}",
    response_model=ResponseEnvelope[EmployeeSkillEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_skill(
    skill_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetEmployeeSkillUseCase = Depends(get_skill_use_case),
):
    _require_email(claims)
    result = await use_case.execute(skill_id)
    return ResponseEnvelope(status="success", data=result)
