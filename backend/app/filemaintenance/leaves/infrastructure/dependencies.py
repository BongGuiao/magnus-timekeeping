from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.leaves.application.use_case import (
    CreateLeaveTypeUseCase,
    GetLeaveTypeUseCase,
    ListLeaveTypesUseCase,
    UpdateLeaveTypeUseCase,
)


def get_create_leave_type_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateLeaveTypeUseCase:
    return CreateLeaveTypeUseCase(uow)


def get_get_leave_type_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetLeaveTypeUseCase:
    return GetLeaveTypeUseCase(uow)


def get_list_leave_types_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListLeaveTypesUseCase:
    return ListLeaveTypesUseCase(uow)


def get_update_leave_type_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateLeaveTypeUseCase:
    return UpdateLeaveTypeUseCase(uow)
