from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID


PAY_COMPONENT_MINUTES = {
    "REGULAR": "regular_minutes",
    "PAID_LEAVE": "paid_leave_minutes",
    "OFFICIAL_BUSINESS": "official_business_minutes",
    "REST_DAY": "rest_day_minutes",
    "SPECIAL_DAY": "special_day_minutes",
    "HOLIDAY": "holiday_minutes",
    "ORDINARY_OT": "ordinary_ot_minutes",
    "REST_DAY_OT": "rest_day_ot_minutes",
    "SPECIAL_DAY_OT": "special_day_ot_minutes",
    "HOLIDAY_OT": "holiday_ot_minutes",
    "NIGHT_REGULAR": "night_regular_minutes",
    "NIGHT_OT": "night_ot_minutes",
}
PAY_COMPONENT_CODES = tuple(PAY_COMPONENT_MINUTES)
MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class Compensation:
    id: UUID
    employee_id: UUID
    payroll_group_id: UUID
    base_rate: Decimal
    currency: str
    effective_from: date
    effective_to: date | None
    is_active: bool


@dataclass(frozen=True)
class EarningRule:
    component_code: str
    multiplier: Decimal


@dataclass(frozen=True)
class PayrollGroupPolicy:
    payroll_group_id: UUID
    rate_type: Literal["MONTHLY", "DAILY", "HOURLY"]
    standard_minutes_per_day: int
    annual_divisor: Decimal | None


@dataclass(frozen=True)
class CutoffEmployeeTime:
    employee_id: UUID
    cutoff_result_id: UUID
    employee_confirmation_status: str
    supervisor_status: str
    hr_status: str
    component_minutes: dict[str, int]
    incomplete_time_source_count: int = 0


@dataclass(frozen=True)
class CutoffPayrollData:
    cutoff_id: UUID
    cutoff_code: str
    period_start: date
    period_end: date
    is_locked: bool
    payroll_group: PayrollGroupPolicy
    employees: tuple[CutoffEmployeeTime, ...]


@dataclass(frozen=True)
class GrossPayLine:
    component_code: str
    minutes: int
    multiplier: Decimal
    amount: Decimal


@dataclass(frozen=True)
class GrossPayResult:
    employee_id: UUID
    cutoff_result_id: UUID
    currency: str | None
    base_rate: Decimal | None
    gross_amount: Decimal | None
    status: Literal["HOLD", "READY"]
    hold_reason: str | None
    lines: tuple[GrossPayLine, ...]
    source_minutes: dict[str, int]
    gross_status: Literal["HOLD", "READY"] | None = None
    cash_benefit_amount: Decimal | None = None
    non_cash_benefit_amount: Decimal | None = None
    employee_benefit_deductions: Decimal | None = None
    exempt_limited_benefit_amount: Decimal | None = None
    taxable_income: Decimal | None = None
    employee_contributions: Decimal | None = None
    employer_contributions: Decimal | None = None
    withholding_tax: Decimal | None = None
    net_amount: Decimal | None = None
    benefit_lines: tuple["PayrollBenefitLine", ...] = ()
    contribution_lines: tuple["PayrollContributionLine", ...] = ()


@dataclass(frozen=True)
class PayrollBenefitLine:
    benefit_code: str
    benefit_name: str
    category: str
    tax_treatment: str
    amount: Decimal


@dataclass(frozen=True)
class PayrollContributionLine:
    program_code: str
    employee_amount: Decimal
    employer_amount: Decimal


@dataclass(frozen=True)
class GrossPayRun:
    id: UUID
    cutoff_id: UUID
    calculation_version: str
    calculated_at: datetime
    calculated_by: UUID
    results: tuple[GrossPayResult, ...]


def base_rate_per_minute(policy: PayrollGroupPolicy, base_rate: Decimal) -> Decimal:
    if base_rate <= 0:
        raise ValueError("Employee base rate must be greater than zero.")
    if policy.standard_minutes_per_day <= 0:
        raise ValueError("Payroll group standard minutes per day must be greater than zero.")
    if policy.rate_type == "HOURLY":
        return base_rate / Decimal(60)
    if policy.rate_type == "DAILY":
        return base_rate / Decimal(policy.standard_minutes_per_day)
    if policy.annual_divisor is None or policy.annual_divisor <= 0:
        raise ValueError("A positive annual divisor is required for monthly salary conversion.")
    return (
        base_rate * Decimal(12)
        / policy.annual_divisor
        / Decimal(policy.standard_minutes_per_day)
    )


def monthly_compensation_basis(
    policy: PayrollGroupPolicy,
    compensation: Compensation | None,
) -> Decimal | None:
    if compensation is None:
        return None
    if policy.rate_type == "MONTHLY":
        return compensation.base_rate.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if policy.annual_divisor is None or policy.annual_divisor <= 0:
        return None
    if policy.rate_type == "DAILY":
        annual_rate = compensation.base_rate * policy.annual_divisor
    else:
        annual_rate = (
            compensation.base_rate
            * Decimal(policy.standard_minutes_per_day)
            * policy.annual_divisor
            / Decimal(60)
        )
    return (annual_rate / Decimal(12)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def calculate_gross_pay(
    *,
    time: CutoffEmployeeTime,
    compensation: Compensation | None,
    policy: PayrollGroupPolicy,
    earning_rules: dict[str, EarningRule],
    cutoff_period_start: date,
    cutoff_period_end: date,
) -> GrossPayResult:
    source_minutes = {
        code: max(0, int(time.component_minutes.get(field, 0)))
        for code, field in PAY_COMPONENT_MINUTES.items()
    }
    if compensation is None:
        return GrossPayResult(
            employee_id=time.employee_id,
            cutoff_result_id=time.cutoff_result_id,
            currency=None,
            base_rate=None,
            gross_amount=None,
            status="HOLD",
            hold_reason=(
                "A unique active employment assignment and compensation must cover "
                "the entire payroll cutoff."
            ),
            lines=(),
            source_minutes=source_minutes,
        )
    if (
        compensation.employee_id != time.employee_id
        or compensation.payroll_group_id != policy.payroll_group_id
        or not compensation.is_active
        or compensation.effective_from > cutoff_period_start
        or (compensation.effective_to is not None and compensation.effective_to < cutoff_period_end)
    ):
        return GrossPayResult(
            employee_id=time.employee_id,
            cutoff_result_id=time.cutoff_result_id,
            currency=None,
            base_rate=None,
            gross_amount=None,
            status="HOLD",
            hold_reason="Compensation must be active for this employee and payroll group throughout the cutoff.",
            lines=(),
            source_minutes=source_minutes,
        )

    if time.incomplete_time_source_count > 0:
        return GrossPayResult(
            employee_id=time.employee_id,
            cutoff_result_id=time.cutoff_result_id,
            currency=compensation.currency,
            base_rate=compensation.base_rate,
            gross_amount=None,
            status="HOLD",
            hold_reason=(
                f"{time.incomplete_time_source_count} worked attendance record(s) "
                "are missing approved worked-time minutes."
            ),
            lines=(),
            source_minutes=source_minutes,
        )

    missing_rules = sorted(set(PAY_COMPONENT_CODES) - earning_rules.keys())
    if missing_rules:
        return GrossPayResult(
            employee_id=time.employee_id,
            cutoff_result_id=time.cutoff_result_id,
            currency=compensation.currency,
            base_rate=compensation.base_rate,
            gross_amount=None,
            status="HOLD",
            hold_reason=f"Missing earning rules: {', '.join(missing_rules)}.",
            lines=(),
            source_minutes=source_minutes,
        )

    try:
        minute_rate = base_rate_per_minute(policy, compensation.base_rate)
    except ValueError as error:
        return GrossPayResult(
            employee_id=time.employee_id,
            cutoff_result_id=time.cutoff_result_id,
            currency=compensation.currency,
            base_rate=compensation.base_rate,
            gross_amount=None,
            status="HOLD",
            hold_reason=str(error),
            lines=(),
            source_minutes=source_minutes,
        )

    lines = tuple(
        GrossPayLine(
            component_code=code,
            minutes=source_minutes[code],
            multiplier=earning_rules[code].multiplier,
            amount=(
                minute_rate
                * Decimal(source_minutes[code])
                * earning_rules[code].multiplier
            ).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP),
        )
        for code in PAY_COMPONENT_CODES
    )
    gross_amount = sum((line.amount for line in lines), Decimal(0)).quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    ready = all(
        status == "ACKNOWLEDGED"
        for status in (
            time.employee_confirmation_status,
            time.supervisor_status,
            time.hr_status,
        )
    )
    return GrossPayResult(
        employee_id=time.employee_id,
        cutoff_result_id=time.cutoff_result_id,
        currency=compensation.currency,
        base_rate=compensation.base_rate,
        gross_amount=gross_amount,
        status="READY" if ready else "HOLD",
        hold_reason=None if ready else "Employee, supervisor, and HR acknowledgments are required.",
        lines=lines,
        source_minutes=source_minutes,
    )
