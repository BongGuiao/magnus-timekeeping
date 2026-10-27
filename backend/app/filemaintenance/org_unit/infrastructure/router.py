from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from elasticsearch import AsyncElasticsearch
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.org_unit.application.use_case import (
    CreateOrgUnitUseCase,
    CreateOrgUnitTypeUseCase,
    GetOrgUnitTypeUseCase,
    GetOrgUnitUseCase,
    ListOrgUnitsUseCase,
    ListOrgUnitTypesUseCase,
    OrgUnitTypeConflictError,
    UpdateOrgUnitTypeUseCase,
    UpdateOrgUnitUseCase,
)
from app.filemaintenance.org_unit.domain.entities.org_unit import OrgUnitEntity
from app.filemaintenance.org_unit.domain.entities.org_unit_type import OrgUnitTypeEntity
from app.filemaintenance.org_unit.infrastructure.dependencies import (
    get_create_org_unit_use_case,
    get_create_org_unit_type_use_case,
    get_list_org_units_use_case,
    get_list_org_unit_types_use_case,
    get_org_unit_use_case,
    get_org_unit_type_use_case,
    get_update_org_unit_type_use_case,
    get_update_org_unit_use_case,
)

router = APIRouter(
    prefix="/org-units",
    tags=["Org Units"],
    dependencies=[Depends(require_permission("company.setup"))],
)


def _require_email(claims: dict[str, Any]) -> None:
    if not claims.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token.",
        )


def _get_user_id(claims: dict[str, Any]) -> UUID:
    _require_email(claims)
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error


class OrgUnitTypeCreateSchema(BaseModel):
    company_id: UUID
    org_unit_type: str = Field(min_length=1, max_length=30)
    display_name: str = Field(min_length=1, max_length=50)
    sort_order: int = Field(ge=0)
    is_default: bool = False
    is_active: bool = True

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @model_validator(mode="after")
    def validate_default_active(self) -> "OrgUnitTypeCreateSchema":
        if self.is_default and not self.is_active:
            raise ValueError("An inactive org unit type cannot be the default.")
        return self

    @field_validator("org_unit_type")
    @classmethod
    def normalize_org_unit_type(cls, value: str) -> str:
        normalized = value.upper()
        if not all(character.isalnum() or character in "_-" for character in normalized):
            raise ValueError("Org unit type must contain only letters, numbers, hyphens, and underscores.")
        return normalized


class OrgUnitTypeUpdateSchema(BaseModel):
    display_name: str = Field(min_length=1, max_length=50)
    sort_order: int = Field(ge=0)
    is_default: bool
    is_active: bool

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @model_validator(mode="after")
    def validate_default_active(self) -> "OrgUnitTypeUpdateSchema":
        if self.is_default and not self.is_active:
            raise ValueError("An inactive org unit type cannot be the default.")
        return self


@router.post(
    "/create",
    response_model=ResponseEnvelope[OrgUnitEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_org_unit(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateOrgUnitUseCase = Depends(get_create_org_unit_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    result = await use_case.execute(
        stamp_audit_fields(payload, user_id, creating=True)
    )
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="CREATE",
        resource="org_unit",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[OrgUnitEntity],
    status_code=status.HTTP_200_OK,
)
async def update_org_unit(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateOrgUnitUseCase = Depends(get_update_org_unit_use_case),
    get_use_case: GetOrgUnitUseCase = Depends(get_org_unit_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    stamp_audit_fields(payload, user_id, creating=False)

    org_unit_id = payload.pop("id", None)
    if not org_unit_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Org unit id is required.",
        )
    try:
        parsed_org_unit_id = UUID(str(org_unit_id))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Org unit id must be a UUID.",
        ) from error

    before = await get_use_case.execute(parsed_org_unit_id)
    result = await use_case.execute(parsed_org_unit_id, payload)
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="UPDATE",
        resource="org_unit",
        resource_id=parsed_org_unit_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[OrgUnitEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_org_units(
    company_id: UUID | None = Query(default=None),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListOrgUnitsUseCase = Depends(get_list_org_units_use_case),
):
    _require_email(claims)
    result = await use_case.execute(company_id)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/types",
    response_model=ResponseEnvelope[list[OrgUnitTypeEntity]],
    status_code=status.HTTP_200_OK,
    summary="List organization unit types",
    description=(
        "Returns active organization unit type lookup values ordered by sort order. "
        "Requires the company.setup permission."
    ),
)
async def list_org_unit_types(
    company_id: UUID = Query(...),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListOrgUnitTypesUseCase = Depends(get_list_org_unit_types_use_case),
):
    _require_email(claims)
    result = await use_case.execute(company_id)
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/types/create",
    response_model=ResponseEnvelope[OrgUnitTypeEntity],
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization unit type",
    description=(
        "Creates a type for organization units. Org-unit type codes are unique and "
        "immutable after creation. Setting a type as the default clears the previous default."
    ),
)
async def create_org_unit_type(
    payload: OrgUnitTypeCreateSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateOrgUnitTypeUseCase = Depends(get_create_org_unit_type_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    values = payload.model_dump(mode="python")
    try:
        result = await use_case.execute(values)
    except OrgUnitTypeConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="CREATE",
        resource="org_unit_type",
        resource_id=result.org_unit_type,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/types/{org_unit_type}",
    response_model=ResponseEnvelope[OrgUnitTypeEntity],
    status_code=status.HTTP_200_OK,
    summary="Update an organization unit type",
    description=(
        "Updates the display name, sort order, default status, or active status. "
        "The type code is immutable; deactivate a type instead of deleting it."
    ),
)
async def update_org_unit_type(
    org_unit_type: str,
    payload: OrgUnitTypeUpdateSchema,
    company_id: UUID = Query(...),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateOrgUnitTypeUseCase = Depends(get_update_org_unit_type_use_case),
    get_use_case: GetOrgUnitTypeUseCase = Depends(get_org_unit_type_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    normalized_type = org_unit_type.strip().upper()
    before = await get_use_case.execute(company_id, normalized_type)
    if before is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization unit type '{normalized_type}' not found.",
        )
    try:
        result = await use_case.execute(
            company_id,
            normalized_type,
            payload.model_dump(mode="python"),
        )
    except OrgUnitTypeConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Org unit type not found.")
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="UPDATE",
        resource="org_unit_type",
        resource_id=normalized_type,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{org_unit_id}",
    response_model=ResponseEnvelope[OrgUnitEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_org_unit(
    org_unit_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetOrgUnitUseCase = Depends(get_org_unit_use_case),
):
    _require_email(claims)
    result = await use_case.execute(org_unit_id)
    return ResponseEnvelope(status="success", data=result)
