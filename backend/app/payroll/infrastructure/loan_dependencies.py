from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.payroll.application.loan_use_cases import EmployeeLoanUseCases
from app.payroll.infrastructure.loan_repository import SqlAlchemyLoanRepository


def get_employee_loan_use_cases(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> EmployeeLoanUseCases:
    return EmployeeLoanUseCases(SqlAlchemyLoanRepository(uow))
