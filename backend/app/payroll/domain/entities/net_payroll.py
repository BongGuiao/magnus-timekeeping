from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.payroll.domain.entities.benefits import CutoffBenefit
from app.payroll.domain.entities.statutory_schedules import (
    ContributionBracket,
    ContributionProgram,
    WithholdingTaxBracket,
    WithholdingTaxSchedule,
)


@dataclass(frozen=True)
class NetPayrollInputs:
    benefits: tuple[CutoffBenefit, ...]
    contribution_brackets: dict[ContributionProgram, tuple[ContributionBracket, ...]]
    tax_schedule: WithholdingTaxSchedule | None
    tax_brackets: tuple[WithholdingTaxBracket, ...]
    monthly_cutoff_count: int
    cutoff_number_in_month: int
    prior_month_employee_contributions: dict[ContributionProgram, Decimal]
    prior_month_employer_contributions: dict[ContributionProgram, Decimal]
    prior_ytd_taxable_income: Decimal
    prior_ytd_withholding_tax: Decimal
    prior_ytd_limited_exempt_benefits: Decimal
    statutory_contribution_timing: Literal["PER_CUTOFF", "FINAL_CUTOFF"] = "PER_CUTOFF"
    pay_frequency: Literal["WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY"] = "SEMIMONTHLY"
    cutoff_half: Literal["FIRST_HALF", "SECOND_HALF"] | None = None
    is_final_december_cutoff: bool = False
    opening_ytd_balance_missing: bool = False
    scheduled_days: Decimal = Decimal(0)
    paid_days: Decimal = Decimal(0)
    required_work_minutes: int = 0
    late_minutes: int = 0
    undertime_minutes: int = 0


@dataclass(frozen=True)
class OpeningYtdBalance:
    id: UUID
    employee_id: UUID
    tax_year: int
    taxable_income: Decimal
    tax_withheld: Decimal
    exempt_limited_benefits: Decimal
    created_at: datetime
    created_by: UUID
    previous_balance_id: UUID | None
