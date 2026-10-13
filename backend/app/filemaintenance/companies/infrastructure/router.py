from typing import Any, Dict, List
from uuid import UUID
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from elasticsearch import AsyncElasticsearch

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.companies.domain.entities.company import CompanyEntity
from app.filemaintenance.companies.application.use_case import CreateCompanyUseCase, GetCompanyUseCase, ListCompaniesUseCase, UpdateCompanyUseCase
from app.filemaintenance.companies.infrastructure.dependencies import (
    get_company_use_case,
    get_create_company_use_case, 
    get_update_company_use_case,
    get_list_companies_use_case
)
from app.filemaintenance.location.application.use_case import ListLocationsUseCase
from app.filemaintenance.location.domain.entities.location import LocationEntity
from app.filemaintenance.location.infrastructure.dependencies import get_list_locations_use_case

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.post(
    "/create",
    response_model=ResponseEnvelope[CompanyEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_company(
    payload: Dict[str, Any],
    claims: dict = Depends(get_current_user_claims),
    use_case: CreateCompanyUseCase = Depends(get_create_company_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = uuid.UUID(claims.get("sub"))
    if not claims.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token."
        )

    result = await use_case.execute(
        stamp_audit_fields(payload, user_id, creating=True)
    )
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="CREATE",
        resource="company",
        resource_id=result.id,
        after=result,
    )

    return ResponseEnvelope(status="success", data=result)

@router.put(
    "/update",
    response_model=ResponseEnvelope[CompanyEntity],
    status_code=status.HTTP_200_OK,
)
async def update_company(
    payload: Dict[str, Any],
    claims: dict = Depends(get_current_user_claims),
    use_case: UpdateCompanyUseCase = Depends(get_update_company_use_case),
    get_use_case: GetCompanyUseCase = Depends(get_company_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    user_id = uuid.UUID(claims.get("sub"))
    if not claims.get("email"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token."
        )
    stamp_audit_fields(payload, user_id, creating=False)

    company_id = payload.pop("id", None)
    if not company_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Company id is required.")
    try:
        parsed_company_id = UUID(str(company_id))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Company id must be a UUID.") from error

    before = await get_use_case.execute(parsed_company_id)
    result = await use_case.execute(parsed_company_id, payload)
    await log_entity_action(
        es_client,
        user_id=user_id,
        action="UPDATE",
        resource="company",
        resource_id=parsed_company_id,
        before=before,
        after=result,
    )

    return ResponseEnvelope(status="success", data=result)

@router.get(
    "/list",
    response_model=ResponseEnvelope[List[CompanyEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_companies(
    claims: dict = Depends(get_current_user_claims),
    use_case: ListCompaniesUseCase = Depends(get_list_companies_use_case),
):
    email = claims.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token."
        )

    result = await use_case.execute()

    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{company_id}/locations",
    response_model=ResponseEnvelope[List[LocationEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_company_locations(
    company_id: UUID,
    claims: dict = Depends(get_current_user_claims),
    use_case: ListLocationsUseCase = Depends(get_list_locations_use_case),
):
    email = claims.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token.",
        )

    result = await use_case.execute(company_id)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{company_id}",
    response_model=ResponseEnvelope[CompanyEntity],
    status_code=status.HTTP_200_OK,
)
async def get_company(
    company_id: UUID,
    claims: dict = Depends(get_current_user_claims),
    use_case: GetCompanyUseCase = Depends(get_company_use_case),
):
    email = claims.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email claim missing from authentication token."
        )

    result = await use_case.execute(company_id)

    return ResponseEnvelope(status="success", data=result)