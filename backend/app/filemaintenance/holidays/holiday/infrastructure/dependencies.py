from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.holidays.holiday.application.use_case import (
    CreateHolidayUseCase,
    GetHolidayUseCase,
    ListHolidaysUseCase,
    UpdateHolidayUseCase,
)


def get_create_holiday_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateHolidayUseCase:
    return CreateHolidayUseCase(uow)


def get_update_holiday_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateHolidayUseCase:
    return UpdateHolidayUseCase(uow)


def get_holiday_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetHolidayUseCase:
    return GetHolidayUseCase(uow)


def get_list_holidays_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListHolidaysUseCase:
    return ListHolidaysUseCase(uow)
