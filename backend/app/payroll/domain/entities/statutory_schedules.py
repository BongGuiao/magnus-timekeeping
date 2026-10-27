from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID


ContributionProgram = Literal["SSS", "PHILHEALTH", "PAGIBIG"]
ScheduleStatus = Literal["DRAFT", "ACTIVE", "RETIRED"]
BRACKET_STEP = Decimal("0.01")


@dataclass(frozen=True)
class ContributionBracket:
    id: UUID
    schedule_id: UUID
    bracket_number: int
    compensation_min: Decimal
    compensation_max: Decimal | None
    contribution_base: Decimal
    employee_rate: Decimal
    employer_rate: Decimal
    employee_fixed_amount: Decimal
    employer_fixed_amount: Decimal
    employer_additional_fixed_amount: Decimal
    employee_contribution_cap: Decimal | None = None
    employer_contribution_cap: Decimal | None = None


@dataclass(frozen=True)
class ContributionSchedule:
    id: UUID
    program_code: ContributionProgram
    schedule_name: str
    effective_from: date
    effective_to: date | None
    source_reference: str
    status: ScheduleStatus
    created_at: datetime
    created_by: UUID | None
    updated_at: datetime
    updated_by: UUID | None
    row_version: int


@dataclass(frozen=True)
class WithholdingTaxBracket:
    id: UUID
    schedule_id: UUID
    bracket_number: int
    annual_income_min: Decimal
    annual_income_max: Decimal | None
    base_tax: Decimal
    marginal_rate: Decimal
    excess_over: Decimal


@dataclass(frozen=True)
class WithholdingTaxSchedule:
    id: UUID
    schedule_name: str
    effective_from: date
    effective_to: date | None
    tax_exempt_benefit_limit: Decimal
    source_reference: str
    status: ScheduleStatus
    created_at: datetime
    created_by: UUID | None
    updated_at: datetime
    updated_by: UUID | None
    row_version: int
    calculation_basis: Literal["ANNUAL_YTD", "SEMI_MONTHLY"] = "ANNUAL_YTD"


def validate_schedule_values(
    *,
    schedule_name: str,
    effective_from: date,
    effective_to: date | None,
    source_reference: str,
) -> None:
    if not schedule_name.strip():
        raise ValueError("Schedule name is required.")
    if not source_reference.strip():
        raise ValueError("A source reference is required.")
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("effective_to must be on or after effective_from.")


def validate_contribution_bracket_values(
    *,
    bracket_number: int,
    compensation_min: Decimal,
    compensation_max: Decimal | None,
    contribution_base: Decimal,
    employee_rate: Decimal,
    employer_rate: Decimal,
    employee_fixed_amount: Decimal,
    employer_fixed_amount: Decimal,
    employer_additional_fixed_amount: Decimal,
    employee_contribution_cap: Decimal | None = None,
    employer_contribution_cap: Decimal | None = None,
) -> None:
    if bracket_number < 1:
        raise ValueError("Bracket number must be greater than zero.")
    if compensation_min < 0 or (compensation_max is not None and compensation_max < compensation_min):
        raise ValueError("Contribution bracket compensation range is invalid.")
    if contribution_base < 0:
        raise ValueError("Contribution base cannot be negative.")
    if not Decimal(0) <= employee_rate <= Decimal(1):
        raise ValueError("Employee contribution rate must be between zero and one.")
    if not Decimal(0) <= employer_rate <= Decimal(1):
        raise ValueError("Employer contribution rate must be between zero and one.")
    if min(employee_fixed_amount, employer_fixed_amount, employer_additional_fixed_amount) < 0:
        raise ValueError("Contribution amounts cannot be negative.")
    if min(
        employee_contribution_cap if employee_contribution_cap is not None else Decimal(0),
        employer_contribution_cap if employer_contribution_cap is not None else Decimal(0),
    ) < 0:
        raise ValueError("Contribution caps cannot be negative.")


def validate_withholding_tax_bracket_values(
    *,
    bracket_number: int,
    annual_income_min: Decimal,
    annual_income_max: Decimal | None,
    base_tax: Decimal,
    marginal_rate: Decimal,
    excess_over: Decimal,
) -> None:
    if bracket_number < 1:
        raise ValueError("Bracket number must be greater than zero.")
    if annual_income_min < 0 or (
        annual_income_max is not None and annual_income_max < annual_income_min
    ):
        raise ValueError("Withholding tax taxable-income range is invalid.")
    if base_tax < 0 or excess_over < 0:
        raise ValueError("Withholding tax amounts cannot be negative.")
    if not Decimal(0) <= marginal_rate <= Decimal(1):
        raise ValueError("Marginal tax rate must be between zero and one.")


def validate_complete_bracket_ranges(
    brackets: list[tuple[int, Decimal, Decimal | None]],
) -> None:
    if not brackets:
        raise ValueError("An active schedule must contain at least one bracket.")

    ordered = sorted(brackets, key=lambda item: item[1])
    if ordered[0][1] != Decimal(0):
        raise ValueError("The first bracket must begin at zero.")
    if [item[0] for item in ordered] != list(range(1, len(ordered) + 1)):
        raise ValueError("Schedule bracket numbers must be sequential from one.")

    for index, (number, lower, upper) in enumerate(ordered):
        if number < 1 or lower < 0 or (upper is not None and upper < lower):
            raise ValueError("Schedule bracket ranges are invalid.")
        is_last = index == len(ordered) - 1
        if upper is None:
            if not is_last:
                raise ValueError("Only the final bracket may have no upper limit.")
            continue
        if is_last:
            raise ValueError("The final bracket must have no upper limit.")
        next_lower = ordered[index + 1][1]
        if next_lower != upper + BRACKET_STEP:
            raise ValueError("Schedule brackets must be ordered and cover each amount exactly once.")
