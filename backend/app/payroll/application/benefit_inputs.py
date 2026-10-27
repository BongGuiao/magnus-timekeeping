from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from datetime import date
from decimal import Decimal
from app.payroll.domain.entities.benefits import (
    BenefitCategory,
    BenefitDeductionSchedule,
    BenefitPostingSchedule,
    BenefitTaxTreatment,
    BenefitWithholdingTiming,
)


@dataclass(frozen=True)
class BenefitTypeInput:
    payroll_group_id: UUID
    code: str
    name: str
    category: BenefitCategory
    tax_treatment: BenefitTaxTreatment
    actor_id: UUID
    attendance_based: bool = False
    deduct_for_late: bool = False
    deduct_for_undertime: bool = False
    posting_schedule: BenefitPostingSchedule = "EVERY_CUTOFF"
    withholding_timing: BenefitWithholdingTiming = "PAY_PERIOD"


@dataclass(frozen=True)
class CutoffBenefitInput:
    cutoff_id: UUID
    employee_id: UUID
    benefit_type_id: UUID
    amount: Decimal
    notes: str | None
    actor_id: UUID


@dataclass(frozen=True)
class CutoffBenefitUploadRow:
    employee_no: str
    benefit_code: str
    amount: Decimal
    notes: str | None


@dataclass(frozen=True)
class EmployeeBenefitDeductionInput:
    employee_id: UUID
    benefit_type_id: UUID
    amount_per_occurrence: Decimal
    schedule: BenefitDeductionSchedule
    effective_from: date
    effective_to: date | None
    actor_id: UUID


@dataclass(frozen=True)
class EmployeeBenefitEntitlementInput:
    employee_id: UUID
    benefit_type_id: UUID
    amount_per_occurrence: Decimal
    schedule: BenefitPostingSchedule
    effective_from: date
    effective_to: date | None
    actor_id: UUID
