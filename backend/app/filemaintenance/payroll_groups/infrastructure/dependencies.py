from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.payroll_groups.application.use_case import (
    CreatePayrollGroupUseCase,
    GetPayrollGroupUseCase,
    ListPayrollGroupsUseCase,
    UpdatePayrollGroupUseCase,
)


def get_create_payroll_group_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreatePayrollGroupUseCase:
    return CreatePayrollGroupUseCase(uow)


def get_get_payroll_group_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetPayrollGroupUseCase:
    return GetPayrollGroupUseCase(uow)


def get_list_payroll_groups_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListPayrollGroupsUseCase:
    return ListPayrollGroupsUseCase(uow)


def get_update_payroll_group_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdatePayrollGroupUseCase:
    return UpdatePayrollGroupUseCase(uow)
