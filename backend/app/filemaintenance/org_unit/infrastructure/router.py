from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from elasticsearch import AsyncElasticsearch

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims, require_permission
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.org_unit.application.use_case import (
    CreateOrgUnitUseCase,
    GetOrgUnitUseCase,
    ListOrgUnitsUseCase,
    UpdateOrgUnitUseCase,
)
from app.filemaintenance.org_unit.domain.entities.org_unit import OrgUnitEntity
from app.filemaintenance.org_unit.infrastructure.dependencies import (
    get_create_org_unit_use_case,
    get_list_org_units_use_case,
    get_org_unit_use_case,
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
