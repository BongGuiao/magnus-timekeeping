from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, status

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.holidays.calendar.application.use_case import (
    CreateHolidayCalendarUseCase,
    GetHolidayCalendarUseCase,
    ListHolidayCalendarsUseCase,
    UpdateHolidayCalendarUseCase,
)
from app.filemaintenance.holidays.calendar.domain.entities.holiday_calendar import (
    HolidayCalendarEntity,
)
from app.filemaintenance.holidays.calendar.infrastructure.dependencies import (
    get_create_holiday_calendar_use_case,
    get_holiday_calendar_use_case,
    get_list_holiday_calendars_use_case,
    get_update_holiday_calendar_use_case,
)

router = APIRouter(prefix="/holiday-calendars", tags=["Holiday Calendars"])


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
    response_model=ResponseEnvelope[HolidayCalendarEntity],
    status_code=status.HTTP_201_CREATED,
)
async def create_holiday_calendar(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: CreateHolidayCalendarUseCase = Depends(get_create_holiday_calendar_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    result = await use_case.execute(stamp_audit_fields(payload, actor_id, creating=True))
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="CREATE",
        resource="holiday_calendar",
        resource_id=result.id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.put(
    "/update",
    response_model=ResponseEnvelope[HolidayCalendarEntity],
    status_code=status.HTTP_200_OK,
)
async def update_holiday_calendar(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: UpdateHolidayCalendarUseCase = Depends(get_update_holiday_calendar_use_case),
    es_client: AsyncElasticsearch | None = Depends(get_audit_es_client),
):
    actor_id = _get_user_id(claims)
    stamp_audit_fields(payload, actor_id, creating=False)
    calendar_id = payload.pop("id", None)
    if not calendar_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Holiday calendar id is required.",
        )
    try:
        parsed_calendar_id = UUID(str(calendar_id))
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Holiday calendar id must be a UUID.",
        ) from error

    result = await use_case.execute(parsed_calendar_id, payload)
    await log_entity_action(
        es_client,
        user_id=actor_id,
        action="UPDATE",
        resource="holiday_calendar",
        resource_id=parsed_calendar_id,
        after=result,
    )
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/list",
    response_model=ResponseEnvelope[list[HolidayCalendarEntity]],
    status_code=status.HTTP_200_OK,
)
async def list_holiday_calendars(
    company_id: UUID | None = None,
    effective_year: int | None = None,
    calendar_status: str | None = None,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: ListHolidayCalendarsUseCase = Depends(get_list_holiday_calendars_use_case),
):
    _require_email(claims)
    result = await use_case.execute(company_id, effective_year, calendar_status)
    return ResponseEnvelope(status="success", data=result)


@router.get(
    "/{calendar_id}",
    response_model=ResponseEnvelope[HolidayCalendarEntity | None],
    status_code=status.HTTP_200_OK,
)
async def get_holiday_calendar(
    calendar_id: UUID,
    claims: dict[str, Any] = Depends(get_current_user_claims),
    use_case: GetHolidayCalendarUseCase = Depends(get_holiday_calendar_use_case),
):
    _require_email(claims)
    result = await use_case.execute(calendar_id)
    return ResponseEnvelope(status="success", data=result)
