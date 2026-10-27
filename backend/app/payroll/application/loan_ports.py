from typing import Protocol
from uuid import UUID

from app.payroll.application.loan_inputs import (
    EmployeeLoanInput,
    RestructureEmployeeLoanInput,
)
from app.payroll.domain.entities.loans import EmployeeLoan


class LoanRepository(Protocol):
    async def list_employee_loans(self, payroll_group_id: UUID) -> list[EmployeeLoan]: ...

    async def create_employee_loan(self, data: EmployeeLoanInput) -> EmployeeLoan: ...

    async def retire_employee_loan(self, loan_id: UUID) -> EmployeeLoan: ...

    async def restructure_employee_loan(
        self, loan_id: UUID, data: RestructureEmployeeLoanInput
    ) -> EmployeeLoan: ...
