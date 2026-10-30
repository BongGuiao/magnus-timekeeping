from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.generics.mapper import ResponseEnvelope
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.infrastructure.router import _get_user_id, _require_email
from app.filemaintenance.operational_groups.application.use_case import (
    CreateOperationalGroupUseCase,
    ListOperationalGroupsUseCase,
    OperationalGroupConflictError,
    OperationalGroupNotFoundError,
    UpdateOperationalGroupUseCase,
)
from app.filemaintenance.operational_groups.domain.entities.operational_group import OperationalGroupEntity

router = APIRouter(prefix="/operational-groups", tags=["Operational Groups"])


class OperationalGroupUpdateSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    display_name: str = Field(min_length=1, max_length=50)
    sort_order: int = Field(ge=0)
    is_active: bool


class OperationalGroupCreateSchema(OperationalGroupUpdateSchema):
    company_id: UUID
    operational_group: str = Field(min_length=1, max_length=30)

    @field_validator("operational_group")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        if not value.isascii() or not all(character.isalnum() or character in "_-" for character in value):
            raise ValueError("Use letters, numbers, hyphens, or underscores for the group code.")
        return value.upper()


def get_list_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> ListOperationalGroupsUseCase:
    return ListOperationalGroupsUseCase(uow)


def get_create_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> CreateOperationalGroupUseCase:
    return CreateOperationalGroupUseCase(uow)


def get_update_use_case(uow: GenUnitOfWork = Depends(get_unit_of_work)) -> UpdateOperationalGroupUseCase:
    return UpdateOperationalGroupUseCase(uow)


@router.get("/list", response_model=ResponseEnvelope[list[OperationalGroupEntity]])
async def list_operational_groups(
    company_id: UUID = Query(...),
    include_inactive: bool = Query(False),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListOperationalGroupsUseCase = Depends(get_list_use_case),
):
    _require_email(claims)
    result = await use_case.execute(company_id, include_inactive)
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/create",
    response_model=ResponseEnvelope[OperationalGroupEntity],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("company.setup"))],
)
async def create_operational_group(
    payload: OperationalGroupCreateSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateOperationalGroupUseCase = Depends(get_create_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    try:
        result = await use_case.execute(payload.model_dump(mode="python"))
    except OperationalGroupConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await log_entity_action(
        es_client, user_id=user_id, action="CREATE", resource="operational_group",
        resource_id=f"{result.company_id}:{result.operational_group}", after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/{code}",
    response_model=ResponseEnvelope[OperationalGroupEntity],
    dependencies=[Depends(require_permission("company.setup"))],
)
async def update_operational_group(
    code: str,
    payload: OperationalGroupUpdateSchema,
    company_id: UUID = Query(...),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateOperationalGroupUseCase = Depends(get_update_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    try:
        before, result = await use_case.execute(company_id, code.strip().upper(), payload.model_dump(mode="python"))
    except OperationalGroupNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    await log_entity_action(
        es_client, user_id=user_id, action="UPDATE", resource="operational_group",
        resource_id=f"{company_id}:{result.operational_group}", before=before, after=result,
    )
    return ResponseEnvelope(status="success", data=result)
