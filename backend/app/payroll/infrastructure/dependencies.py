from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.payroll.application.use_cases import PayrollUseCases
from app.payroll.application.statutory_schedule_use_cases import StatutoryScheduleUseCases
from app.payroll.application.benefit_use_cases import BenefitUseCases
from app.payroll.infrastructure.benefit_repository import SqlAlchemyBenefitRepository
from app.payroll.infrastructure.repository import SqlAlchemyPayrollRepository
from app.payroll.infrastructure.statutory_schedule_repository import (
    SqlAlchemyStatutoryScheduleRepository,
)


def get_payroll_use_cases(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> PayrollUseCases:
    return PayrollUseCases(SqlAlchemyPayrollRepository(uow))


def get_statutory_schedule_use_cases(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> StatutoryScheduleUseCases:
    return StatutoryScheduleUseCases(SqlAlchemyStatutoryScheduleRepository(uow))


def get_benefit_use_cases(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> BenefitUseCases:
    return BenefitUseCases(SqlAlchemyBenefitRepository(uow))
