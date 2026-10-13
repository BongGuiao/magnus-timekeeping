from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from elasticsearch import AsyncElasticsearch

from app.audit.domain import AuditLogCreate
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_action
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.audit_logging import log_entity_change, stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.location.application.use_case import (
    CreateLocationUseCase,
    GetLocationUseCase,
    ListLocationsUseCase,
    UpdateLocationUseCase,
)
from app.filemaintenance.location.domain.entities.location import LocationEntity
from app.filemaintenance.location.infrastructure.dependencies import (
    get_create_location_use_case,
    get_list_locations_use_case,
    get_location_use_case,
    get_update_location_use_case,
)

router = APIRouter(prefix="/locations", tags=["Locations"])


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
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListLocationsUseCase = Depends(get_list_locations_use_case),
):
    _require_email(claims)
    result = await use_case.execute(company_id)
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
