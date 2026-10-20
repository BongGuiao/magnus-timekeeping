from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.payroll.domain.entities.statutory_schedules import ContributionProgram


@dataclass(frozen=True)
class ContributionScheduleInput:
    program_code: ContributionProgram
    schedule_name: str
    effective_from: date
    effective_to: date | None
    source_reference: str
    actor_id: UUID


@dataclass(frozen=True)
class ContributionBracketInput:
    bracket_number: int
    compensation_min: Decimal
    compensation_max: Decimal | None
    contribution_base: Decimal
    employee_rate: Decimal
    employer_rate: Decimal
    employee_fixed_amount: Decimal
    employer_fixed_amount: Decimal
    employer_additional_fixed_amount: Decimal


@dataclass(frozen=True)
class WithholdingTaxScheduleInput:
    schedule_name: str
    effective_from: date
    effective_to: date | None
    tax_exempt_benefit_limit: Decimal
    source_reference: str
    actor_id: UUID


@dataclass(frozen=True)
class WithholdingTaxBracketInput:
    bracket_number: int
    annual_income_min: Decimal
    annual_income_max: Decimal | None
    base_tax: Decimal
    marginal_rate: Decimal
    excess_over: Decimal
