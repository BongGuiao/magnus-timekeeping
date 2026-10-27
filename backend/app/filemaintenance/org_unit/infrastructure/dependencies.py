from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.org_unit.application.use_case import (
    CreateOrgUnitUseCase,
    CreateOrgUnitTypeUseCase,
    GetOrgUnitTypeUseCase,
    GetOrgUnitUseCase,
    ListOrgUnitsUseCase,
    ListOrgUnitTypesUseCase,
    UpdateOrgUnitTypeUseCase,
    UpdateOrgUnitUseCase,
)


def get_create_org_unit_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateOrgUnitUseCase:
    return CreateOrgUnitUseCase(uow)


def get_update_org_unit_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateOrgUnitUseCase:
    return UpdateOrgUnitUseCase(uow)


def get_org_unit_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetOrgUnitUseCase:
    return GetOrgUnitUseCase(uow)


def get_list_org_units_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListOrgUnitsUseCase:
    return ListOrgUnitsUseCase(uow)


def get_list_org_unit_types_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListOrgUnitTypesUseCase:
    return ListOrgUnitTypesUseCase(uow)


def get_create_org_unit_type_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateOrgUnitTypeUseCase:
    return CreateOrgUnitTypeUseCase(uow)


def get_org_unit_type_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetOrgUnitTypeUseCase:
    return GetOrgUnitTypeUseCase(uow)


def get_update_org_unit_type_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateOrgUnitTypeUseCase:
    return UpdateOrgUnitTypeUseCase(uow)
