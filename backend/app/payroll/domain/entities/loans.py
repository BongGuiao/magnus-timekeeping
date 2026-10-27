from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID


LoanSchedule = Literal["FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"]
LoanCutoffHalf = Literal["FIRST_HALF", "SECOND_HALF"]
LoanStatus = Literal["ACTIVE", "RETIRED", "PAID_OFF"]


@dataclass(frozen=True)
class EmployeeLoanRepayment:
    id: UUID
    loan_id: UUID
    cutoff_id: UUID
    gross_pay_run_id: UUID
    amount: Decimal
    created_at: datetime
    cutoff_code: str


@dataclass(frozen=True)
class EmployeeLoan:
    id: UUID
    employee_id: UUID
    payroll_group_id: UUID
    reference_number: str
    principal_amount: Decimal
    installment_amount: Decimal
    schedule: LoanSchedule
    effective_from: date
    outstanding_balance: Decimal
    status: LoanStatus
    previous_loan_id: UUID | None
    created_at: datetime
    repayments: tuple[EmployeeLoanRepayment, ...] = ()


def validate_loan_values(
    *,
    reference_number: str,
    principal_amount: Decimal,
    installment_amount: Decimal,
    schedule: LoanSchedule,
) -> None:
    if not reference_number.strip() or len(reference_number.strip()) > 50:
        raise ValueError("Loan reference number must contain 1 to 50 characters.")
    if not principal_amount.is_finite() or principal_amount <= 0:
        raise ValueError("Loan principal must be a finite amount greater than zero.")
    if not installment_amount.is_finite() or installment_amount <= 0:
        raise ValueError("Loan installment must be a finite amount greater than zero.")
    if schedule not in {"FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"}:
        raise ValueError("Loan deduction schedule is invalid.")


def loan_due_this_cutoff(
    schedule: LoanSchedule,
    cutoff_half: LoanCutoffHalf | None,
) -> bool:
    if schedule == "EVERY_CUTOFF":
        return True
    if cutoff_half is None:
        raise ValueError(
            "Assign this payroll cutoff as First or Second before calculating "
            "scheduled loan repayments."
        )
    if schedule == "FIRST_HALF":
        return cutoff_half == "FIRST_HALF"
    if schedule == "SECOND_HALF":
        return cutoff_half == "SECOND_HALF"
    raise ValueError("Loan deduction schedule is invalid.")


def loan_installment_due(
    installment_amount: Decimal,
    outstanding_balance: Decimal,
) -> Decimal:
    if outstanding_balance <= 0:
        return Decimal(0)
    return min(installment_amount, outstanding_balance)


def restructured_principal(
    outstanding_balance: Decimal,
    additional_principal: Decimal,
) -> Decimal:
    if not outstanding_balance.is_finite() or outstanding_balance <= 0:
        raise ValueError("A loan with an outstanding balance is required for restructuring.")
    if not additional_principal.is_finite() or additional_principal < 0:
        raise ValueError("Additional principal must be a finite nonnegative amount.")
    return outstanding_balance + additional_principal
