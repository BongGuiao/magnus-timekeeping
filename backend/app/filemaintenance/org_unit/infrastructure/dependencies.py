from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.org_unit.application.use_case import (
    CreateOrgUnitUseCase,
    GetOrgUnitUseCase,
    ListOrgUnitsUseCase,
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
