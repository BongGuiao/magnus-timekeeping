from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from elasticsearch import AsyncElasticsearch
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.dependencies import get_audit_es_client
from app.audit.service import log_entity_action
from app.auth.infrastructure.dependencies import get_current_user_claims
from app.auth.infrastructure.db_model import UserModel
from app.core.database import get_db
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import ResponseEnvelope
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentModel,
)
from app.filemaintenance.holidays.calendar.domain.scope import (
    GeographicArea,
    holiday_applies_to_location,
)
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
from app.filemaintenance.location.infrastructure.db_model import Location as LocationModel

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
    holidays = await session.execute(
        select(HolidayModel, HolidayCalendarModel, LocationModel)
        .select_from(HolidayModel)
        .join(
            HolidayCalendarModel,
            HolidayCalendarModel.id == HolidayModel.holiday_calendar_id,
        )
        .join(
            EmploymentAssignmentModel,
            and_(
                EmploymentAssignmentModel.company_id == HolidayCalendarModel.company_id,
                EmploymentAssignmentModel.effective_from <= HolidayModel.holiday_date,
                or_(
                    EmploymentAssignmentModel.effective_to.is_(None),
                    EmploymentAssignmentModel.effective_to >= HolidayModel.holiday_date,
                ),
                EmploymentAssignmentModel.is_active.is_(True),
                EmploymentAssignmentModel.status == "ACTIVE",
                or_(
                    EmploymentAssignmentModel.separation_date.is_(None),
                    EmploymentAssignmentModel.separation_date >= HolidayModel.holiday_date,
                ),
            ),
        )
        .join(EmployeeModel, EmployeeModel.id == EmploymentAssignmentModel.employee_id)
        .join(UserModel, UserModel.employee_id == EmployeeModel.id)
        .outerjoin(
            LocationModel,
            LocationModel.id == EmploymentAssignmentModel.primary_location_id,
        )
        .where(
            UserModel.id == user_id,
            UserModel.is_active.is_(True),
            UserModel.account_status == "ACTIVE",
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
            HolidayCalendarModel.effective_year >= today.year,
            HolidayCalendarModel.status == "PUBLISHED",
            HolidayCalendarModel.is_active.is_(True),
            HolidayModel.holiday_date >= today,
            HolidayModel.holiday_date <= today + timedelta(days=days),
            HolidayModel.status == "ACTIVE",
            HolidayModel.is_active.is_(True),
        )
        .order_by(HolidayModel.holiday_date, HolidayModel.holiday_name)
    )
    upcoming_holidays: set[tuple[date, str]] = set()
    for holiday, calendar, location in holidays:
        if calendar.effective_year != holiday.holiday_date.year:
            continue
        location_area = location or GeographicArea()
        if holiday_applies_to_location(
            holiday.holiday_type,
            holiday,
            location_area,
        ):
            upcoming_holidays.add((holiday.holiday_date, holiday.holiday_name))

    return ResponseEnvelope(
        status="success",
        data=[
            UpcomingHolidaySchema(date=holiday_date, name=holiday_name)
            for holiday_date, holiday_name in sorted(upcoming_holidays)[:100]
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
