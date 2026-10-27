from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.payroll.domain.entities.benefits import (
    BenefitCategory,
    BenefitTaxTreatment,
    BenefitType,
    BenefitWithholdingTiming,
)


OffCycleRunType = Literal["BENEFIT", "THIRTEENTH_MONTH"]
OffCycleRunStatus = Literal["DRAFT", "PENDING", "APPROVED", "PAID", "REJECTED"]
OffCycleAction = Literal["RECALCULATE", "SUBMIT", "APPROVE", "REJECT", "MARK_PAID", "DELETE"]

OFF_CYCLE_CASH_CATEGORIES: frozenset[str] = frozenset(
    {"ONE_TIME_BONUS", "CASH_ALLOWANCE", "REIMBURSEMENT"}
)
OFF_CYCLE_ALLOWED_STATUSES: dict[OffCycleAction, frozenset[str]] = {
    "RECALCULATE": frozenset({"DRAFT"}),
    "SUBMIT": frozenset({"DRAFT"}),
    "APPROVE": frozenset({"PENDING"}),
    "REJECT": frozenset({"PENDING", "APPROVED"}),
    "MARK_PAID": frozenset({"APPROVED"}),
    "DELETE": frozenset({"DRAFT", "REJECTED"}),
}
OFF_CYCLE_YTD_STATUSES: frozenset[str] = frozenset({"PAID"})


@dataclass(frozen=True)
class OffCyclePayrollLine:
    id: UUID
    run_id: UUID
    employee_id: UUID
    employee_no: str
    employee_name: str
    benefit_code: str
    benefit_name: str
    category: BenefitCategory
    tax_treatment: BenefitTaxTreatment
    withholding_timing: BenefitWithholdingTiming
    amount: Decimal
    taxable_amount: Decimal
    exempt_limited_amount: Decimal
    withholding_tax: Decimal
    net_amount: Decimal
    notes: str | None
    thirteenth_month_result_id: UUID | None = None


@dataclass(frozen=True)
class OffCyclePayrollRun:
    id: UUID
    company_id: UUID
    payroll_group_id: UUID
    benefit_type_id: UUID
    benefit_code: str
    benefit_name: str
    run_type: OffCycleRunType
    status: OffCycleRunStatus
    proposed_payment_date: date
    actual_payment_date: date | None
    notes: str | None
    rejection_reason: str | None
    created_by: UUID
    created_at: datetime
    submitted_at: datetime | None
    approved_by: UUID | None
    approved_at: datetime | None
    paid_by: UUID | None
    paid_at: datetime | None
    thirteenth_month_run_id: UUID | None
    lines: tuple[OffCyclePayrollLine, ...] = ()

    @property
    def total_amount(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal(0))

    @property
    def total_withholding_tax(self) -> Decimal:
        return sum((line.withholding_tax for line in self.lines), Decimal(0))

    @property
    def total_net_amount(self) -> Decimal:
        return sum((line.net_amount for line in self.lines), Decimal(0))


def ensure_off_cycle_action_allowed(status: str, action: OffCycleAction) -> None:
    if status not in OFF_CYCLE_ALLOWED_STATUSES[action]:
        allowed = ", ".join(sorted(OFF_CYCLE_ALLOWED_STATUSES[action]))
        raise ValueError(
            f"This off-cycle run is {status}; {action.replace('_', ' ').lower()} "
            f"is only allowed when the run is {allowed}."
        )


def ensure_off_cycle_approver(created_by: UUID, approver_id: UUID) -> None:
    if created_by == approver_id:
        raise PermissionError(
            "The user who prepared this off-cycle run cannot approve it."
        )


def validate_off_cycle_benefit_type(
    benefit_type: BenefitType, run_type: OffCycleRunType
) -> None:
    if not benefit_type.is_active:
        raise ValueError(f"Benefit type {benefit_type.code} is inactive.")
    if benefit_type.category not in OFF_CYCLE_CASH_CATEGORIES:
        raise ValueError(
            "Off-cycle runs only pay cash benefits. Choose a One-time bonus, "
            "Cash allowance, or Reimbursement benefit type."
        )
    if run_type == "THIRTEENTH_MONTH" and (
        benefit_type.category != "ONE_TIME_BONUS"
        or benefit_type.tax_treatment != "EXEMPT_LIMITED"
    ):
        raise ValueError(
            "13th-month pay must use a One-time bonus benefit type with "
            "Exempt up to limit tax treatment."
        )


def validate_off_cycle_payment_dates(
    proposed_payment_date: date, actual_payment_date: date | None = None
) -> None:
    if proposed_payment_date.year < 1900 or proposed_payment_date.year > 9999:
        raise ValueError("Proposed payment date is invalid.")
    if actual_payment_date is not None and actual_payment_date.year != proposed_payment_date.year:
        raise ValueError(
            "The actual payment date must fall in the same tax year as the proposed "
            "payment date. Create a new run for a different tax year."
        )


def validate_off_cycle_amount(amount: Decimal) -> None:
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Off-cycle amounts must be finite and greater than zero.")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Off-cycle amounts can have at most two decimal places.")
