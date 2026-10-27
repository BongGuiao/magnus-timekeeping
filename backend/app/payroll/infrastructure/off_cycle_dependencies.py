from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.payroll.application.off_cycle_use_cases import OffCyclePayrollUseCases
from app.payroll.infrastructure.off_cycle_repository import SqlAlchemyOffCyclePayrollRepository


def get_off_cycle_payroll_use_cases(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> OffCyclePayrollUseCases:
    return OffCyclePayrollUseCases(SqlAlchemyOffCyclePayrollRepository(uow))
