from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.payroll.domain.entities.off_cycle import OffCycleRunStatus, OffCycleRunType


@dataclass(frozen=True)
class OffCycleUploadRow:
    employee_no: str
    amount: Decimal
    notes: str | None = None


@dataclass(frozen=True)
class CreateOffCycleBenefitRunInput:
    payroll_group_id: UUID
    benefit_type_id: UUID
    proposed_payment_date: date
    rows: tuple[OffCycleUploadRow, ...]
    actor_id: UUID
    notes: str | None = None


@dataclass(frozen=True)
class CreateThirteenthMonthOffCycleRunInput:
    payroll_group_id: UUID
    benefit_type_id: UUID
    thirteenth_month_run_id: UUID
    proposed_payment_date: date
    actor_id: UUID
    notes: str | None = None


@dataclass(frozen=True)
class OffCycleEmployee:
    employee_id: UUID
    employee_no: str
    employee_name: str


@dataclass(frozen=True)
class ThirteenthMonthPayable:
    result_id: UUID
    employee_id: UUID
    employee_no: str
    employee_name: str
    amount: Decimal


@dataclass(frozen=True)
class ThirteenthMonthRunSummary:
    id: UUID
    tax_year: int
    covered_period_from: date | None
    covered_period_to: date | None
    calculated_at: datetime
    result_count: int


@dataclass(frozen=True)
class OffCycleLineDraft:
    employee_id: UUID
    employee_no: str
    amount: Decimal
    taxable_amount: Decimal
    exempt_limited_amount: Decimal
    withholding_tax: Decimal
    net_amount: Decimal
    notes: str | None = None
    thirteenth_month_result_id: UUID | None = None


@dataclass(frozen=True)
class NewOffCycleRun:
    company_id: UUID
    payroll_group_id: UUID
    benefit_type_id: UUID
    run_type: OffCycleRunType
    proposed_payment_date: date
    created_by: UUID
    lines: tuple[OffCycleLineDraft, ...]
    notes: str | None = None
    thirteenth_month_run_id: UUID | None = None


@dataclass(frozen=True)
class OffCycleRunTransition:
    """State change applied atomically when the run is still in ``expected_status``."""

    expected_status: OffCycleRunStatus
    new_status: OffCycleRunStatus
    occurred_at: datetime
    actor_id: UUID
    rejection_reason: str | None = None
    actual_payment_date: date | None = None
