from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.leaves.application.leave_records_use_case import (
    EmployeeEntitlementUseCase,
    LeaveApplicationDateUseCase,
    LeaveApplicationUseCase,
    LeaveLedgerUseCase,
)


def get_employee_entitlement_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> EmployeeEntitlementUseCase:
    return EmployeeEntitlementUseCase(uow)


def get_leave_application_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> LeaveApplicationUseCase:
    return LeaveApplicationUseCase(uow)


def get_leave_application_date_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> LeaveApplicationDateUseCase:
    return LeaveApplicationDateUseCase(uow)


def get_leave_ledger_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> LeaveLedgerUseCase:
    return LeaveLedgerUseCase(uow)
