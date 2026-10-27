from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID


BenefitCategory = Literal[
    "CASH_ALLOWANCE",
    "ONE_TIME_BONUS",
    "REIMBURSEMENT",
    "EMPLOYER_PAID_INSURANCE",
    "NON_CASH",
    "EMPLOYEE_DEDUCTION",
]
BenefitTaxTreatment = Literal["TAXABLE", "EXEMPT", "EXEMPT_LIMITED"]
BenefitWithholdingTiming = Literal["PAY_PERIOD", "YEAR_END"]
BenefitDeductionSchedule = Literal["FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"]
BenefitPostingSchedule = Literal["FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"]
CutoffHalf = Literal["FIRST_HALF", "SECOND_HALF"]


@dataclass(frozen=True)
class BenefitType:
    id: UUID
    payroll_group_id: UUID
    code: str
    name: str
    category: BenefitCategory
    tax_treatment: BenefitTaxTreatment
    is_active: bool
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: UUID
    row_version: int
    attendance_based: bool = False
    deduct_for_late: bool = False
    deduct_for_undertime: bool = False
    posting_schedule: BenefitPostingSchedule = "EVERY_CUTOFF"
    withholding_timing: BenefitWithholdingTiming = "PAY_PERIOD"


@dataclass(frozen=True)
class CutoffBenefit:
    id: UUID
    cutoff_id: UUID
    employee_id: UUID
    benefit_type_id: UUID
    benefit_code: str
    benefit_name: str
    category: BenefitCategory
    tax_treatment: BenefitTaxTreatment
    amount: Decimal
    notes: str | None
    attendance_based: bool = False
    deduct_for_late: bool = False
    deduct_for_undertime: bool = False
    withholding_timing: BenefitWithholdingTiming = "PAY_PERIOD"
    loan_id: UUID | None = None


@dataclass(frozen=True)
class EmployeeBenefitDeduction:
    id: UUID
    employee_id: UUID
    benefit_type_id: UUID
    benefit_code: str
    benefit_name: str
    amount_per_occurrence: Decimal
    schedule: BenefitDeductionSchedule
    effective_from: date
    effective_to: date | None
    is_active: bool


@dataclass(frozen=True)
class EmployeeBenefitEntitlement:
    id: UUID
    employee_id: UUID
    benefit_type_id: UUID
    benefit_code: str
    benefit_name: str
    amount_per_occurrence: Decimal
    schedule: BenefitPostingSchedule
    effective_from: date
    effective_to: date | None
    is_active: bool


def validate_benefit_type_values(
    *,
    code: str,
    name: str,
    category: BenefitCategory,
    tax_treatment: BenefitTaxTreatment,
    attendance_based: bool = False,
    deduct_for_late: bool = False,
    deduct_for_undertime: bool = False,
    posting_schedule: BenefitPostingSchedule = "EVERY_CUTOFF",
    withholding_timing: BenefitWithholdingTiming = "PAY_PERIOD",
) -> None:
    if not code.strip() or len(code.strip()) > 30:
        raise ValueError("Benefit code must contain 1 to 30 characters.")
    if not name.strip() or len(name.strip()) > 120:
        raise ValueError("Benefit name must contain 1 to 120 characters.")
    if posting_schedule not in {"FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"}:
        raise ValueError("Benefit posting schedule is invalid.")
    if withholding_timing not in {"PAY_PERIOD", "YEAR_END"}:
        raise ValueError("Benefit withholding timing is invalid.")
    if withholding_timing == "YEAR_END" and (
        category != "ONE_TIME_BONUS" or tax_treatment != "TAXABLE"
    ):
        raise ValueError(
            "Year-end withholding is available only for taxable one-time bonuses."
        )
    if category == "EMPLOYEE_DEDUCTION" and tax_treatment != "EXEMPT":
        raise ValueError("Employee benefit deductions must use EXEMPT tax treatment.")
    if category == "EMPLOYEE_DEDUCTION" and attendance_based:
        raise ValueError("Recurring employee deductions cannot be attendance-based benefits.")
    if not attendance_based and (deduct_for_late or deduct_for_undertime):
        raise ValueError("Enable attendance-based calculation before enabling time deductions.")


def validate_cutoff_benefit_amount(amount: Decimal) -> None:
    if not amount.is_finite() or amount <= Decimal(0):
        raise ValueError("Benefit amount must be a finite amount greater than zero.")


def validate_employee_benefit_deduction_values(
    *,
    amount_per_occurrence: Decimal,
    schedule: BenefitDeductionSchedule,
    effective_from: date,
    effective_to: date | None,
) -> None:
    if not amount_per_occurrence.is_finite() or amount_per_occurrence <= Decimal(0):
        raise ValueError("Deduction amount per occurrence must be a finite amount greater than zero.")
    if schedule not in {"FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"}:
        raise ValueError("Employee deduction schedule is invalid.")
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("Deduction end date must be on or after its start date.")


def validate_employee_benefit_entitlement_values(
    *,
    amount_per_occurrence: Decimal,
    schedule: BenefitPostingSchedule,
    effective_from: date,
    effective_to: date | None,
) -> None:
    if not amount_per_occurrence.is_finite() or amount_per_occurrence <= Decimal(0):
        raise ValueError("Benefit amount per occurrence must be a finite amount greater than zero.")
    if schedule not in {"FIRST_HALF", "SECOND_HALF", "EVERY_CUTOFF"}:
        raise ValueError("Employee benefit schedule is invalid.")
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("Benefit end date must be on or after its start date.")


def is_benefit_due(
    schedule: BenefitPostingSchedule,
    cutoff_half: CutoffHalf | None,
) -> bool:
    if schedule == "EVERY_CUTOFF":
        return True
    if cutoff_half is None:
        raise ValueError(
            "Assign this payroll cutoff as First or Second before calculating "
            "scheduled benefits."
        )
    if schedule == "FIRST_HALF":
        return cutoff_half == "FIRST_HALF"
    if schedule == "SECOND_HALF":
        return cutoff_half == "SECOND_HALF"
    raise ValueError("Benefit posting schedule is invalid.")


def is_employee_deduction_due(
    schedule: BenefitDeductionSchedule,
    cutoff_half: CutoffHalf | None,
) -> bool:
    if schedule == "EVERY_CUTOFF":
        return True
    if cutoff_half is None:
        raise ValueError(
            "Assign this payroll cutoff as First or Second before calculating "
            "scheduled employee deductions."
        )
    if schedule == "FIRST_HALF":
        return cutoff_half == "FIRST_HALF"
    if schedule == "SECOND_HALF":
        return cutoff_half == "SECOND_HALF"
    raise ValueError("Employee deduction schedule is invalid.")
