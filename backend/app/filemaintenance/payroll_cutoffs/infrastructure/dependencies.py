from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.payroll_cutoffs.application.use_case import (
    CreatePayrollCutoffUseCase,
    GetPayrollCutoffUseCase,
    ListPayrollCutoffsUseCase,
    UpdatePayrollCutoffUseCase,
)


def get_create_payroll_cutoff_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreatePayrollCutoffUseCase:
    return CreatePayrollCutoffUseCase(uow)


def get_get_payroll_cutoff_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetPayrollCutoffUseCase:
    return GetPayrollCutoffUseCase(uow)


def get_list_payroll_cutoffs_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListPayrollCutoffsUseCase:
    return ListPayrollCutoffsUseCase(uow)


def get_update_payroll_cutoff_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdatePayrollCutoffUseCase:
    return UpdatePayrollCutoffUseCase(uow)
