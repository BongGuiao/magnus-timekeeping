from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.holidays.calendar.application.use_case import (
    CreateHolidayCalendarUseCase,
    GetHolidayCalendarUseCase,
    ListHolidayCalendarsUseCase,
    UpdateHolidayCalendarUseCase,
)


def get_create_holiday_calendar_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateHolidayCalendarUseCase:
    return CreateHolidayCalendarUseCase(uow)


def get_update_holiday_calendar_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateHolidayCalendarUseCase:
    return UpdateHolidayCalendarUseCase(uow)


def get_holiday_calendar_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetHolidayCalendarUseCase:
    return GetHolidayCalendarUseCase(uow)


def get_list_holiday_calendars_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListHolidayCalendarsUseCase:
    return ListHolidayCalendarsUseCase(uow)
