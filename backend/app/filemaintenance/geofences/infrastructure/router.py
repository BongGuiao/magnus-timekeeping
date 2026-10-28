from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from elasticsearch import AsyncElasticsearch

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import (
    get_current_user_claims,
    require_any_permission,
    require_permission,
)
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.geofences.application.use_case import (
    CreateGeofenceUseCase,
    DeleteGeofenceUseCase,
    GetGeofenceUseCase,
    ListGeofencesUseCase,
    UpdateGeofenceUseCase,
)
from app.filemaintenance.geofences.domain.entities.geofence import GeofenceEntity
from app.filemaintenance.geofences.infrastructure.dependencies import (
    get_create_geofence_use_case,
    get_delete_geofence_use_case,
    get_geofence_use_case,
    get_list_geofences_use_case,
    get_update_geofence_use_case,
)

router = APIRouter(
    prefix="/geofences",
    tags=["Geofences"],
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


@router.post(
    "/create",
    response_model=ResponseEnvelope[GeofenceEntity],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("company.setup"))],
)
async def create_geofence(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateGeofenceUseCase = Depends(get_create_geofence_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    result = await use_case.execute(stamp_audit_fields(payload, user_id, creating=True))
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="CREATE",
        resource="geofence",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[GeofenceEntity],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("company.setup"))],
)
async def update_geofence(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateGeofenceUseCase = Depends(get_update_geofence_use_case),
    get_use_case: GetGeofenceUseCase = Depends(get_geofence_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    stamp_audit_fields(payload, user_id, creating=False)
    geofence_id = payload.pop("id", None)
    if not geofence_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Geofence id is required.",
        )
    try:
        parsed_geofence_id = UUID(str(geofence_id))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Geofence id must be a UUID.",
        ) from error

    before = await get_use_case.execute(parsed_geofence_id)
    result = await use_case.execute(parsed_geofence_id, payload)
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="UPDATE",
        resource="geofence",
        resource_id=parsed_geofence_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[GeofenceEntity]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_any_permission("company.setup", "employees.manage"))],
)
async def list_geofences(
    company_id: UUID | None = None,
    include_deleted: bool = False,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListGeofencesUseCase = Depends(get_list_geofences_use_case),
):
    _require_email(claims)
    result = await use_case.execute(company_id, include_deleted)
    return ResponseEnvelope(status="success", data=result)


@router.delete(
    "/{geofence_id}",
    response_model=ResponseEnvelope[GeofenceEntity],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_permission("company.setup"))],
)
async def delete_geofence(
    geofence_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: DeleteGeofenceUseCase = Depends(get_delete_geofence_use_case),
    get_use_case: GetGeofenceUseCase = Depends(get_geofence_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = _get_user_id(claims)
    before = await get_use_case.execute(geofence_id)
    result = await use_case.execute(geofence_id, user_id)
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="DELETE",
        resource="geofence",
        resource_id=geofence_id,
        before=before,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{geofence_id}",
    response_model=ResponseEnvelope[GeofenceEntity | None],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_any_permission("company.setup", "employees.manage"))],
)
async def get_geofence(
    geofence_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetGeofenceUseCase = Depends(get_geofence_use_case),
):
    _require_email(claims)
    result = await use_case.execute(geofence_id)
    return ResponseEnvelope(status="success", data=result)
