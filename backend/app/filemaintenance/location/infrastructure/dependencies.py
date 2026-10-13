from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.location.application.use_case import (
    CreateLocationUseCase,
    GetLocationUseCase,
    ListLocationsUseCase,
    UpdateLocationUseCase,
)


def get_create_location_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateLocationUseCase:
    return CreateLocationUseCase(uow)


def get_update_location_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateLocationUseCase:
    return UpdateLocationUseCase(uow)


def get_location_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetLocationUseCase:
    return GetLocationUseCase(uow)


def get_list_locations_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListLocationsUseCase:
    return ListLocationsUseCase(uow)
