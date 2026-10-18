from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.core.database import get_db
from app.core.employee_company_scope import get_active_employee_company_ids
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.holidays.calendar.infrastructure.db_model import HolidayCalendarModel
from app.filemaintenance.holidays.holiday.application.use_case import (
    CreateHolidayUseCase,
    GetHolidayUseCase,
    ListHolidaysUseCase,
    UpdateHolidayUseCase,
)
from app.filemaintenance.holidays.holiday.domain.entities.holiday import HolidayEntity
from app.filemaintenance.holidays.holiday.infrastructure.db_model import HolidayModel
from app.filemaintenance.holidays.holiday.infrastructure.dependencies import (
    get_create_holiday_use_case,
    get_holiday_use_case,
    get_list_holidays_use_case,
    get_update_holiday_use_case,
)

router = APIRouter(prefix="/holidays", tags=["Holidays"])
PH_TIMEZONE = ZoneInfo("Asia/Manila")


class UpcomingHolidaySchema(BaseModel):
    date: date
    name: str


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


@router.get(
    "/upcoming",
    response_model=ResponseEnvelope[list[UpcomingHolidaySchema]],
    status_code=status.HTTP_200_OK,
)
async def list_upcoming_holidays(
    days: int = Query(default=90, ge=1, le=366),
    claims: dict[str, Any] = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db),
):
    user_id = _get_user_id(claims)
    today = datetime.now(PH_TIMEZONE).date()
    company_ids = await get_active_employee_company_ids(session, user_id, today)
    if not company_ids:
        return ResponseEnvelope(status="success", data=[])

    holidays = await session.execute(
        select(HolidayModel.holiday_date, HolidayModel.holiday_name)
        .distinct()
        .select_from(HolidayModel)
        .join(
            HolidayCalendarModel,
            HolidayCalendarModel.id == HolidayModel.holiday_calendar_id,
        )
        .where(
            HolidayCalendarModel.company_id.in_(company_ids),
            HolidayCalendarModel.effective_year >= today.year,
            HolidayCalendarModel.status == "PUBLISHED",
            HolidayCalendarModel.is_active.is_(True),
            HolidayModel.holiday_date >= today,
            HolidayModel.holiday_date <= today + timedelta(days=days),
            HolidayModel.status == "ACTIVE",
            HolidayModel.is_active.is_(True),
        )
        .order_by(HolidayModel.holiday_date, HolidayModel.holiday_name)
        .limit(100)
    )
    return ResponseEnvelope(
        status="success",
        data=[
            UpcomingHolidaySchema(date=holiday_date, name=holiday_name)
            for holiday_date, holiday_name in holidays
        ],
    )


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
