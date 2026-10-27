from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from elasticsearch import AsyncElasticsearch

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.application.authorization import GetCurrentAuthorizationUseCase
from app.auth.infrastructure.dependencies import (
    get_current_authorization_use_case,
    get_current_user_claims,
)
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.employees.application.related_use_case import (
    CreateEmploymentAssignmentsBatchUseCase,
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
    get_create_assignments_batch_use_case,
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


PAYROLL_GROUP_FORBIDDEN_DETAIL = "Only HR payroll personnel can set or change an employee's payroll group."


async def _assignment_writer_permissions(
    claims: dict[str, Any] = Depends(get_current_user_claims),
    authorization_use_case: GetCurrentAuthorizationUseCase = Depends(
        get_current_authorization_use_case
    ),
) -> set[str]:
    user_id = _get_user_id(claims)
    authorization = await authorization_use_case.execute(user_id)
    permission_codes = set(authorization.permission_codes)
    if "employees.manage" not in permission_codes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
    return permission_codes


def _normalize_uuid(value: Any) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return value


def ensure_payroll_group_change_allowed(
    permission_codes: set[str],
    payload: dict[str, Any],
    existing_payroll_group_id: UUID | None = None,
) -> None:
    """Payroll group drives payroll processing, so only payroll managers (HR) may set it."""
    if "payroll.manage" in permission_codes or "payroll_group_id" not in payload:
        return
    if _normalize_uuid(payload["payroll_group_id"]) != _normalize_uuid(existing_payroll_group_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PAYROLL_GROUP_FORBIDDEN_DETAIL)


@assignments_router.post(
    "/create",
    response_model=ResponseEnvelope[EmploymentAssignmentEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    permission_codes: set[str] = Depends(_assignment_writer_permissions),
    use_case: CreateEmploymentAssignmentUseCase = Depends(get_create_assignment_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    ensure_payroll_group_change_allowed(permission_codes, payload)
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


@assignments_router.post(
    "/batch-create",
    response_model=ResponseEnvelope[list[EmploymentAssignmentEntity]],
    status_code=status.HTTP_201_CREATED,
)
async def create_assignments_batch(
    payload: list[dict[str, Any]],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    permission_codes: set[str] = Depends(_assignment_writer_permissions),
    use_case: CreateEmploymentAssignmentsBatchUseCase = Depends(get_create_assignments_batch_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    for row in payload:
        if isinstance(row.get("assignment"), dict):
            ensure_payroll_group_change_allowed(permission_codes, row["assignment"])
    try:
        stamped_payload = [
            {
                "row_number": row.get("row_number"),
                "assignment": stamp_audit_fields(row["assignment"], user_id, creating=True)
                if isinstance(row.get("assignment"), dict)
                else row.get("assignment"),
            }
            for row in payload
        ]
        results = await use_case.execute(stamped_payload)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    for result in results:
        await log_entity_action(
            es_client,
            user_id=user_id,
            action="CREATE",
            resource="employment_assignment",
            resource_id=result.id,
            after=result,
        )
    return ResponseEnvelope(status="success", data=results)


@assignments_router.put(
    "/update",
    response_model=ResponseEnvelope[EmploymentAssignmentEntity],
    status_code=status.HTTP_200_OK,
)
async def update_assignment(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    permission_codes: set[str] = Depends(_assignment_writer_permissions),
    use_case: UpdateEmploymentAssignmentUseCase = Depends(get_update_assignment_use_case),
    get_use_case: GetEmploymentAssignmentUseCase = Depends(get_assignment_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    assignment_id = _pop_record_id(payload, "Employment assignment")
    user_id = _get_user_id(claims)
    before = await get_use_case.execute(assignment_id)
    ensure_payroll_group_change_allowed(
        permission_codes,
        payload,
        before.payroll_group_id if before is not None else None,
    )
    stamp_audit_fields(payload, user_id, creating=False)
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
