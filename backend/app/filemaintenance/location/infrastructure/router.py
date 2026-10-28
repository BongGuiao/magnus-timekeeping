from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from elasticsearch import AsyncElasticsearch
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.audit.domain import AuditLogCreate
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_action
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.audit_logging import log_entity_change, stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.location.application.location_type_use_case import (
    CreateLocationTypeUseCase,
    DeleteLocationTypeUseCase,
    GetLocationTypeUseCase,
    ListLocationTypesUseCase,
    LocationTypeConflictError,
    UpdateLocationTypeUseCase,
)
from app.filemaintenance.location.application.use_case import (
    CreateLocationUseCase,
    DeleteLocationUseCase,
    GetLocationUseCase,
    ListLocationsUseCase,
    UpdateLocationUseCase,
)
from app.filemaintenance.location.domain.entities.location import LocationEntity
from app.filemaintenance.location.domain.entities.location_type import LocationTypeEntity
from app.filemaintenance.location.infrastructure.dependencies import (
    get_create_location_type_use_case,
    get_create_location_use_case,
    get_delete_location_use_case,
    get_delete_location_type_use_case,
    get_list_location_types_use_case,
    get_list_locations_use_case,
    get_location_use_case,
    get_location_type_use_case,
    get_update_location_type_use_case,
    get_update_location_use_case,
)

router = APIRouter(
    prefix="/locations",
    tags=["Locations"],
    dependencies=[Depends(require_permission("company.setup"))],
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


def _require_email(claims: dict[str, Any]) -> None:
    if not claims.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token.",
        )


class LocationTypeCreateSchema(BaseModel):
    company_id: UUID
    location_type: str = Field(min_length=1, max_length=30)
    display_name: str = Field(min_length=1, max_length=50)
    sort_order: int = Field(ge=0)
    is_default: bool = False
    is_active: bool = True

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @model_validator(mode="after")
    def validate_default_active(self) -> "LocationTypeCreateSchema":
        if self.is_default and not self.is_active:
            raise ValueError("An inactive location type cannot be the default.")
        return self

    @field_validator("location_type")
    @classmethod
    def normalize_location_type(cls, value: str) -> str:
        normalized = value.upper()
        if not all(character.isalnum() or character in "_-" for character in normalized):
            raise ValueError("Location type must contain only letters, numbers, hyphens, and underscores.")
        return normalized


class LocationTypeUpdateSchema(BaseModel):
    display_name: str = Field(min_length=1, max_length=50)
    sort_order: int = Field(ge=0)
    is_default: bool
    is_active: bool

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @model_validator(mode="after")
    def validate_default_active(self) -> "LocationTypeUpdateSchema":
        if self.is_default and not self.is_active:
            raise ValueError("An inactive location type cannot be the default.")
        return self


def _normalize_location_type(value: str) -> str:
    normalized = value.upper()
    if not all(character.isalnum() or character in "_-" for character in normalized):
        raise ValueError("Location type must contain only letters, numbers, hyphens, and underscores.")
    return normalized

@router.post(
    "/create",
    response_model=ResponseEnvelope[LocationEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_location(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateLocationUseCase = Depends(get_create_location_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    result = await use_case.execute(
        stamp_audit_fields(payload, actor_id, creating=True)
    )
    log_entity_change(
        entity_name="location",
        action="create",
        entity_id=result.id,
        actor_id=actor_id,
        before=None,
        after=result,
    )
    if es_client is not None:
        await log_action(
            es_client,
            AuditLogCreate(
                user_id=str(actor_id),
                action="CREATE",
                resource="location",
                resource_id=str(result.id),
                new_values=asdict(result),
                timestamp=datetime.now(timezone.utc),
            ),
        )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[LocationEntity],
    status_code=status.HTTP_200_OK,
)
async def update_location(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateLocationUseCase = Depends(get_update_location_use_case),
    get_use_case: GetLocationUseCase = Depends(get_location_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    stamp_audit_fields(payload, actor_id, creating=False)
    location_id = payload.pop("id", None)
    if not location_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Location id is required.",
        )
    try:
        parsed_location_id = UUID(str(location_id))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Location id must be a UUID.",
        ) from error

    before = await get_use_case.execute(parsed_location_id)
    result = await use_case.execute(parsed_location_id, payload)
    log_entity_change(
        entity_name="location",
        action="update",
        entity_id=parsed_location_id,
        actor_id=actor_id,
        before=before,
        after=result,
    )
    if es_client is not None:
        await log_action(
            es_client,
            AuditLogCreate(
                user_id=str(actor_id),
                action="UPDATE",
                resource="location",
                resource_id=str(parsed_location_id),
                old_values=asdict(before) if before is not None else None,
                new_values=asdict(result),
                timestamp=datetime.now(timezone.utc),
            ),
        )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[LocationEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_locations(
    company_id: UUID | None = None,
    include_deleted: bool = False,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListLocationsUseCase = Depends(get_list_locations_use_case),
):
    _require_email(claims)
    result = await use_case.execute(company_id, include_deleted)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/types",
    response_model=ResponseEnvelope[list[LocationTypeEntity]],
    status_code=status.HTTP_200_OK,
    summary="List location types",
)
async def list_location_types(
    company_id: UUID,
    include_inactive: bool = False,
    include_deleted: bool = False,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListLocationTypesUseCase = Depends(get_list_location_types_use_case),
):
    _require_email(claims)
    result = await use_case.execute(company_id, include_inactive, include_deleted)
    return ResponseEnvelope(status="success", data=result)


@router.post(
    "/types/create",
    response_model=ResponseEnvelope[LocationTypeEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_location_type(
    payload: LocationTypeCreateSchema,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateLocationTypeUseCase = Depends(get_create_location_type_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    values = payload.model_dump(mode="python")
    values["location_type"] = _normalize_location_type(values["location_type"])
    try:
        result = await use_case.execute(values)
    except LocationTypeConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    log_entity_change(
        entity_name="location_type",
        action="create",
        entity_id=f"{result.company_id}:{result.location_type}",
        actor_id=actor_id,
        before=None,
        after=result,
    )
    if es_client is not None:
        await log_action(
            es_client,
            AuditLogCreate(
                user_id=str(actor_id),
                action="CREATE",
                resource="location_type",
                resource_id=f"{result.company_id}:{result.location_type}",
                new_values=asdict(result),
                timestamp=datetime.now(timezone.utc),
            ),
        )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/types/{location_type}",
    response_model=ResponseEnvelope[LocationTypeEntity],
    status_code=status.HTTP_200_OK,
)
async def update_location_type(
    location_type: str,
    payload: LocationTypeUpdateSchema,
    company_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateLocationTypeUseCase = Depends(get_update_location_type_use_case),
    get_use_case: GetLocationTypeUseCase = Depends(get_location_type_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    normalized_type = _normalize_location_type(location_type.strip())
    before = await get_use_case.execute(company_id, normalized_type)
    if before is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location type '{normalized_type}' not found.",
        )
    try:
        result = await use_case.execute(
            company_id,
            normalized_type,
            payload.model_dump(mode="python"),
        )
    except LocationTypeConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location type not found.")
    log_entity_change(
        entity_name="location_type",
        action="update",
        entity_id=f"{company_id}:{normalized_type}",
        actor_id=actor_id,
        before=before,
        after=result,
    )
    if es_client is not None:
        await log_action(
            es_client,
            AuditLogCreate(
                user_id=str(actor_id),
                action="UPDATE",
                resource="location_type",
                resource_id=f"{company_id}:{normalized_type}",
                old_values=asdict(before),
                new_values=asdict(result),
                timestamp=datetime.now(timezone.utc),
            ),
        )
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/types/{location_type}",
    response_model=ResponseEnvelope[LocationTypeEntity],
    status_code=status.HTTP_200_OK,
)
async def delete_location_type(
    location_type: str,
    company_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: DeleteLocationTypeUseCase = Depends(get_delete_location_type_use_case),
    get_use_case: GetLocationTypeUseCase = Depends(get_location_type_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    normalized_type = _normalize_location_type(location_type.strip())
    before = await get_use_case.execute(company_id, normalized_type)
    result = await use_case.execute(company_id, normalized_type, actor_id)
    resource_id = f"{company_id}:{normalized_type}"
    log_entity_change(
        entity_name="location_type",
        action="delete",
        entity_id=resource_id,
        actor_id=actor_id,
        before=before,
        after=result,
    )
    if es_client is not None:
        await log_action(
            es_client,
            AuditLogCreate(
                user_id=str(actor_id),
                action="DELETE",
                resource="location_type",
                resource_id=resource_id,
                old_values=asdict(before) if before is not None else None,
                new_values=asdict(result),
                timestamp=datetime.now(timezone.utc),
            ),
        )
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/{location_id}",
    response_model=ResponseEnvelope[LocationEntity],
    status_code=status.HTTP_200_OK,
)
async def delete_location(
    location_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: DeleteLocationUseCase = Depends(get_delete_location_use_case),
    get_use_case: GetLocationUseCase = Depends(get_location_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    before = await get_use_case.execute(location_id)
    result = await use_case.execute(location_id, actor_id)
    log_entity_change(
        entity_name="location",
        action="delete",
        entity_id=location_id,
        actor_id=actor_id,
        before=before,
        after=result,
    )
    if es_client is not None:
        await log_action(
            es_client,
            AuditLogCreate(
                user_id=str(actor_id),
                action="DELETE",
                resource="location",
                resource_id=str(location_id),
                old_values=asdict(before) if before is not None else None,
                new_values=asdict(result),
                timestamp=datetime.now(timezone.utc),
            ),
        )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{location_id}",
    response_model=ResponseEnvelope[LocationEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_location(
    location_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetLocationUseCase = Depends(get_location_use_case),
):
    _require_email(claims)
    result = await use_case.execute(location_id)
    return ResponseEnvelope(status="success", data=result)
    get_list_location_types_use_case,
    get_location_type_use_case,
    get_update_location_type_use_case,
