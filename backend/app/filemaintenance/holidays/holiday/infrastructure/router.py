from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.holidays.holiday.application.use_case import (
    CreateHolidayUseCase,
    GetHolidayUseCase,
    ListHolidaysUseCase,
    UpdateHolidayUseCase,
)
from app.filemaintenance.holidays.holiday.domain.entities.holiday import HolidayEntity
from app.filemaintenance.holidays.holiday.infrastructure.dependencies import (
    get_create_holiday_use_case,
    get_holiday_use_case,
    get_list_holidays_use_case,
    get_update_holiday_use_case,
)

router = APIRouter(prefix="/holidays", tags=["Holidays"])


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
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User id claim missing or invalid in authentication token.",
        ) from error


@router.post(
    "/create",
    response_model=ResponseEnvelope[HolidayEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_holiday(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateHolidayUseCase = Depends(get_create_holiday_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    result = await use_case.execute(stamp_audit_fields(payload, actor_id, creating=True))
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="holiday",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[HolidayEntity],
    status_code=status.HTTP_200_OK,
)
async def update_holiday(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateHolidayUseCase = Depends(get_update_holiday_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    stamp_audit_fields(payload, actor_id, creating=False)
    holiday_id = payload.pop("id", None)
    if not holiday_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Holiday id is required.",
        )
    try:
        parsed_holiday_id = UUID(str(holiday_id))
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Holiday id must be a UUID.",
        ) from error

    result = await use_case.execute(parsed_holiday_id, payload)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="holiday",
        resource_id=parsed_holiday_id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[HolidayEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_holidays(
    holiday_calendar_id: UUID | None = None,
    holiday_status: str | None = None,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListHolidaysUseCase = Depends(get_list_holidays_use_case),
):
    _require_email(claims)
    result = await use_case.execute(holiday_calendar_id, holiday_status)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{holiday_id}",
    response_model=ResponseEnvelope[HolidayEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_holiday(
    holiday_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetHolidayUseCase = Depends(get_holiday_use_case),
):
    _require_email(claims)
    result = await use_case.execute(holiday_id)
    return ResponseEnvelope(status="success", data=result)
