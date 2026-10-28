from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.location.application.use_case import (
    CreateLocationUseCase,
    DeleteLocationUseCase,
    GetLocationUseCase,
    ListLocationsUseCase,
    UpdateLocationUseCase,
)
from app.filemaintenance.location.application.location_type_use_case import (
    CreateLocationTypeUseCase,
    DeleteLocationTypeUseCase,
    GetLocationTypeUseCase,
    ListLocationTypesUseCase,
    UpdateLocationTypeUseCase,
)


def get_delete_location_type_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> DeleteLocationTypeUseCase:
    return DeleteLocationTypeUseCase(uow)


def get_list_location_types_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListLocationTypesUseCase:
    return ListLocationTypesUseCase(uow)


def get_create_location_type_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateLocationTypeUseCase:
    return CreateLocationTypeUseCase(uow)


def get_location_type_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetLocationTypeUseCase:
    return GetLocationTypeUseCase(uow)


def get_update_location_type_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateLocationTypeUseCase:
    return UpdateLocationTypeUseCase(uow)


def get_delete_location_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> DeleteLocationUseCase:
    return DeleteLocationUseCase(uow)


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
