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
    pay_frequency: Literal["WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY"]
    standard_minutes_per_day: int
    annual_divisor: Decimal | None


@dataclass(frozen=True)
class CutoffEmployeeTime:
    employee_id: UUID
    cutoff_result_id: UUID
    component_minutes: dict[str, int]
    required_work_minutes: int = 0
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
    is_attendance_finalized: bool = False
    year_end_wtax_reconciliation_enabled: bool = False
    cutoff_half: Literal["FIRST_HALF", "SECOND_HALF"] | None = None


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
    withholding_timing: str = "PAY_PERIOD"
    loan_id: UUID | None = None


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


class PayrollApprovalPermissionError(PermissionError):
    pass


@dataclass(frozen=True)
class PayrollCutoffLockState:
    cutoff_id: UUID
    locked: bool
    locked_at: datetime | None
    locked_by: UUID | None


@dataclass(frozen=True)
class ThirteenthMonthResult:
    employee_id: UUID
    employee_no: str
    employee_name: str
    basic_salary_earned: Decimal
    thirteenth_month_pay: Decimal
    tax_exempt_amount: Decimal
    taxable_amount: Decimal
    source_payroll_periods: int


@dataclass(frozen=True)
class ThirteenthMonthRun:
    id: UUID
    tax_year: int
    covered_period_from: date
    covered_period_to: date
    calculated_at: datetime
    calculated_by: UUID
    results: tuple[ThirteenthMonthResult, ...]


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
    return compensation_period_basis(policy, compensation, periods_per_year=12)


def compensation_period_basis(
    policy: PayrollGroupPolicy,
    compensation: Compensation | None,
    *,
    periods_per_year: int,
) -> Decimal | None:
    if periods_per_year <= 0:
        raise ValueError("Payroll periods per year must be positive.")
    if compensation is None:
        return None
    if policy.rate_type == "MONTHLY":
        annual_rate = compensation.base_rate * Decimal(12)
    else:
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
    return (annual_rate / Decimal(periods_per_year)).quantize(
        MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )


def _monthly_salary_period_amount(
    policy: PayrollGroupPolicy,
    monthly_salary: Decimal,
) -> Decimal:
    periods_per_year = {
        "WEEKLY": Decimal(52),
        "BIWEEKLY": Decimal(26),
        "SEMIMONTHLY": Decimal(24),
        "MONTHLY": Decimal(12),
    }[policy.pay_frequency]
    return (monthly_salary * Decimal(12) / periods_per_year).quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


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

    if policy.rate_type == "MONTHLY":
        covered_minutes = sum(
            source_minutes[code]
            for code in (
                "REGULAR",
                "PAID_LEAVE",
                "OFFICIAL_BUSINESS",
                "SPECIAL_DAY",
                "HOLIDAY",
            )
        )
        unpaid_minutes = max(
            0,
            max(time.required_work_minutes, 0)
            - min(max(time.required_work_minutes, 0), covered_minutes),
        )
        unpaid_amount = (
            minute_rate * Decimal(unpaid_minutes)
        ).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        monthly_base = _monthly_salary_period_amount(policy, compensation.base_rate)
        salary_lines = (
            GrossPayLine(
                component_code="MONTHLY_BASE",
                minutes=0,
                multiplier=Decimal(1),
                amount=monthly_base,
            ),
            GrossPayLine(
                component_code="UNPAID_TIME_DEDUCTION",
                minutes=unpaid_minutes,
                multiplier=Decimal(-1),
                amount=-unpaid_amount,
            ),
        )
        earning_codes = ("REST_DAY", "SPECIAL_DAY", "HOLIDAY") + PAY_COMPONENT_CODES[6:]
        earnings = tuple(
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
            for code in earning_codes
        )
        lines = salary_lines + earnings
    else:
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
    return GrossPayResult(
        employee_id=time.employee_id,
        cutoff_result_id=time.cutoff_result_id,
        currency=compensation.currency,
        base_rate=compensation.base_rate,
        gross_amount=gross_amount,
        status="READY",
        hold_reason=None,
        lines=lines,
        source_minutes=source_minutes,
    )
