from decimal import Decimal
from uuid import UUID

from app.payroll.application.loan_inputs import (
    EmployeeLoanInput,
    RestructureEmployeeLoanInput,
)
from app.payroll.application.loan_ports import LoanRepository
from app.payroll.domain.entities.loans import (
    EmployeeLoan,
    LoanSchedule,
    validate_loan_values,
)


class EmployeeLoanUseCases:
    def __init__(self, repository: LoanRepository):
        self._repository = repository

    async def list_employee_loans(self, payroll_group_id: UUID) -> list[EmployeeLoan]:
        if not payroll_group_id:
            raise ValueError("A payroll group is required.")
        return await self._repository.list_employee_loans(payroll_group_id)

    async def create_employee_loan(self, data: EmployeeLoanInput) -> EmployeeLoan:
        self._validate_input(
            reference_number=data.reference_number,
            principal_amount=data.principal_amount,
            installment_amount=data.installment_amount,
            schedule=data.schedule,
        )
        if not data.employee_id or not data.payroll_group_id:
            raise ValueError("An employee and payroll group are required.")
        return await self._repository.create_employee_loan(data)

    async def retire_employee_loan(self, loan_id: UUID) -> EmployeeLoan:
        if not loan_id:
            raise ValueError("Select a loan to retire.")
        return await self._repository.retire_employee_loan(loan_id)

    async def restructure_employee_loan(
        self, loan_id: UUID, data: RestructureEmployeeLoanInput
    ) -> EmployeeLoan:
        if not loan_id:
            raise ValueError("Select a loan to restructure.")
        if not data.additional_principal.is_finite() or data.additional_principal < 0:
            raise ValueError("Additional principal must be a finite nonnegative amount.")
        self._validate_input(
            reference_number=data.reference_number,
            principal_amount=data.additional_principal,
            installment_amount=data.installment_amount,
            schedule=data.schedule,
            allow_zero_principal=True,
        )
        return await self._repository.restructure_employee_loan(loan_id, data)

    @staticmethod
    def _validate_input(
        *,
        reference_number: str,
        principal_amount: Decimal,
        installment_amount: Decimal,
        schedule: LoanSchedule,
        allow_zero_principal: bool = False,
    ) -> None:
        if allow_zero_principal and principal_amount == 0:
            if not reference_number.strip() or len(reference_number.strip()) > 50:
                raise ValueError("Loan reference number must contain 1 to 50 characters.")
            if not installment_amount.is_finite() or installment_amount <= 0:
                raise ValueError("Loan installment must be a finite amount greater than zero.")
            if schedule not in {"FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"}:
                raise ValueError("Loan deduction schedule is invalid.")
            return
        validate_loan_values(
            reference_number=reference_number,
            principal_amount=principal_amount,
            installment_amount=installment_amount,
            schedule=schedule,
        )
