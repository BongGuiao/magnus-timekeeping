from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from app.payroll.domain.entities.benefits import CutoffBenefit
from app.payroll.domain.entities.gross_payroll import PayrollBenefitLine
from app.payroll.domain.entities.statutory_schedules import (
    ContributionBracket,
    ContributionProgram,
    WithholdingTaxBracket,
    WithholdingTaxSchedule,
)


MONEY_QUANTUM = Decimal("0.01")
REQUIRED_CONTRIBUTION_PROGRAMS: tuple[ContributionProgram, ...] = (
    "SSS",
    "PHILHEALTH",
    "PAGIBIG",
)


@dataclass(frozen=True)
class ContributionLine:
    program_code: ContributionProgram
    employee_amount: Decimal
    employer_amount: Decimal


@dataclass(frozen=True)
class NetPayCalculation:
    status: Literal["HOLD", "READY"]
    hold_reason: str | None
    cash_benefit_amount: Decimal
    non_cash_benefit_amount: Decimal
    employee_benefit_deductions: Decimal
    exempt_limited_benefit_amount: Decimal
    taxable_income: Decimal | None
    employee_contributions: Decimal | None
    employer_contributions: Decimal | None
    withholding_tax: Decimal | None
    net_amount: Decimal | None
    contribution_lines: tuple[ContributionLine, ...]
    benefit_lines: tuple[PayrollBenefitLine, ...]


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _amount_in_bracket(
    amount: Decimal,
    brackets: tuple[ContributionBracket, ...],
) -> ContributionBracket | None:
    return next(
        (
            bracket
            for bracket in brackets
            if bracket.compensation_min <= amount
            and (bracket.compensation_max is None or amount <= bracket.compensation_max)
        ),
        None,
    )


def _tax_due(
    annual_taxable_income: Decimal,
    brackets: tuple[WithholdingTaxBracket, ...],
) -> Decimal | None:
    bracket = next(
        (
            item
            for item in brackets
            if item.annual_income_min <= annual_taxable_income
            and (
                item.annual_income_max is None
                or annual_taxable_income <= item.annual_income_max
            )
        ),
        None,
    )
    if bracket is None:
        return None
    return _money(
        bracket.base_tax
        + max(Decimal(0), annual_taxable_income - bracket.excess_over)
        * bracket.marginal_rate
    )


def _attendance_adjusted_amount(
    benefit: CutoffBenefit,
    *,
    scheduled_days: Decimal,
    paid_days: Decimal,
    required_work_minutes: int,
    late_minutes: int,
    undertime_minutes: int,
) -> Decimal:
    if not benefit.attendance_based:
        return _money(benefit.amount)
    if scheduled_days <= 0:
        return Decimal("0.00")
    paid_day_fraction = min(max(paid_days, Decimal(0)) / scheduled_days, Decimal(1))
    deduction_minutes = (
        (max(late_minutes, 0) if benefit.deduct_for_late else 0)
        + (max(undertime_minutes, 0) if benefit.deduct_for_undertime else 0)
    )
    if deduction_minutes and required_work_minutes <= 0:
        raise ValueError(
            "Required scheduled work minutes are missing for attendance-based benefit deductions."
        )
    deductions = (
        benefit.amount * Decimal(deduction_minutes) / Decimal(required_work_minutes)
        if deduction_minutes
        else Decimal(0)
    )
    return _money(max(Decimal(0), benefit.amount * paid_day_fraction - deductions))


def calculate_net_pay(
    *,
    gross_amount: Decimal,
    benefits: tuple[CutoffBenefit, ...],
    monthly_compensation: Decimal | None,
    contribution_brackets: dict[ContributionProgram, tuple[ContributionBracket, ...]],
    tax_schedule: WithholdingTaxSchedule | None,
    tax_brackets: tuple[WithholdingTaxBracket, ...],
    monthly_cutoff_count: int,
    cutoff_number_in_month: int,
    prior_month_employee_contributions: dict[ContributionProgram, Decimal],
    prior_month_employer_contributions: dict[ContributionProgram, Decimal],
    prior_ytd_taxable_income: Decimal,
    prior_ytd_withholding_tax: Decimal,
    prior_ytd_limited_exempt_benefits: Decimal,
    opening_ytd_balance_missing: bool = False,
    scheduled_days: Decimal = Decimal(0),
    paid_days: Decimal = Decimal(0),
    required_work_minutes: int = 0,
    late_minutes: int = 0,
    undertime_minutes: int = 0,
) -> NetPayCalculation:
    calculated_benefits = tuple(
        replace(
            benefit,
            amount=_attendance_adjusted_amount(
                benefit,
                scheduled_days=scheduled_days,
                paid_days=paid_days,
                required_work_minutes=required_work_minutes,
                late_minutes=late_minutes,
                undertime_minutes=undertime_minutes,
            ),
        )
        for benefit in benefits
    )
    benefit_lines = tuple(
        PayrollBenefitLine(
            benefit_code=benefit.benefit_code,
            benefit_name=benefit.benefit_name,
            category=benefit.category,
            tax_treatment=benefit.tax_treatment,
            amount=_money(benefit.amount),
        )
        for benefit in calculated_benefits
    )
    cash_benefits = sum(
        (
            benefit.amount
            for benefit in calculated_benefits
            if benefit.category
            in {"CASH_ALLOWANCE", "ONE_TIME_BONUS", "REIMBURSEMENT"}
        ),
        Decimal(0),
    )
    non_cash_benefits = sum(
        (
            benefit.amount
            for benefit in calculated_benefits
            if benefit.category in {"EMPLOYER_PAID_INSURANCE", "NON_CASH"}
        ),
        Decimal(0),
    )
    employee_benefit_deductions = sum(
        (
            benefit.amount
            for benefit in calculated_benefits
            if benefit.category == "EMPLOYEE_DEDUCTION"
        ),
        Decimal(0),
    )
    limited_benefits = sum(
        (
            benefit.amount
            for benefit in calculated_benefits
            if benefit.tax_treatment == "EXEMPT_LIMITED"
            and benefit.category != "EMPLOYEE_DEDUCTION"
        ),
        Decimal(0),
    )
    taxable_benefits = sum(
        (
            benefit.amount
            for benefit in calculated_benefits
            if benefit.tax_treatment == "TAXABLE"
            and benefit.category != "EMPLOYEE_DEDUCTION"
        ),
        Decimal(0),
    )

    missing = [
        program
        for program in REQUIRED_CONTRIBUTION_PROGRAMS
        if not contribution_brackets.get(program)
    ]
    if tax_schedule is None or not tax_brackets:
        missing.append("WITHHOLDING_TAX")
    if missing:
        return NetPayCalculation(
            status="HOLD",
            hold_reason=f"Missing active statutory schedules: {', '.join(missing)}.",
            cash_benefit_amount=_money(cash_benefits),
            non_cash_benefit_amount=_money(non_cash_benefits),
            employee_benefit_deductions=_money(employee_benefit_deductions),
            exempt_limited_benefit_amount=_money(limited_benefits),
            taxable_income=None,
            employee_contributions=None,
            employer_contributions=None,
            withholding_tax=None,
            net_amount=None,
            contribution_lines=(),
            benefit_lines=benefit_lines,
        )
    if opening_ytd_balance_missing:
        return NetPayCalculation(
            status="HOLD",
            hold_reason="An employee tax-year opening balance must be recorded before calculating cumulative withholding tax.",
            cash_benefit_amount=_money(cash_benefits),
            non_cash_benefit_amount=_money(non_cash_benefits),
            employee_benefit_deductions=_money(employee_benefit_deductions),
            exempt_limited_benefit_amount=_money(limited_benefits),
            taxable_income=None,
            employee_contributions=None,
            employer_contributions=None,
            withholding_tax=None,
            net_amount=None,
            contribution_lines=(),
            benefit_lines=benefit_lines,
        )
    if monthly_cutoff_count < 1 or not 1 <= cutoff_number_in_month <= monthly_cutoff_count:
        return NetPayCalculation(
            status="HOLD",
            hold_reason="The cutoff's monthly contribution allocation is invalid.",
            cash_benefit_amount=_money(cash_benefits),
            non_cash_benefit_amount=_money(non_cash_benefits),
            employee_benefit_deductions=_money(employee_benefit_deductions),
            exempt_limited_benefit_amount=_money(limited_benefits),
            taxable_income=None,
            employee_contributions=None,
            employer_contributions=None,
            withholding_tax=None,
            net_amount=None,
            contribution_lines=(),
            benefit_lines=benefit_lines,
        )
    if monthly_compensation is None:
        return NetPayCalculation(
            status="HOLD",
            hold_reason="A monthly compensation basis cannot be derived from the configured pay rate.",
            cash_benefit_amount=_money(cash_benefits),
            non_cash_benefit_amount=_money(non_cash_benefits),
            employee_benefit_deductions=_money(employee_benefit_deductions),
            exempt_limited_benefit_amount=_money(limited_benefits),
            taxable_income=None,
            employee_contributions=None,
            employer_contributions=None,
            withholding_tax=None,
            net_amount=None,
            contribution_lines=(),
            benefit_lines=benefit_lines,
        )

    contribution_lines: list[ContributionLine] = []
    for program in REQUIRED_CONTRIBUTION_PROGRAMS:
        bracket = _amount_in_bracket(monthly_compensation, contribution_brackets[program])
        if bracket is None:
            return NetPayCalculation(
                status="HOLD",
                hold_reason=f"No {program} contribution bracket covers monthly compensation.",
                cash_benefit_amount=_money(cash_benefits),
                non_cash_benefit_amount=_money(non_cash_benefits),
                employee_benefit_deductions=_money(employee_benefit_deductions),
                exempt_limited_benefit_amount=_money(limited_benefits),
                taxable_income=None,
                employee_contributions=None,
                employer_contributions=None,
                withholding_tax=None,
                net_amount=None,
                contribution_lines=(),
                benefit_lines=benefit_lines,
            )
        monthly_employee = _money(
            bracket.contribution_base * bracket.employee_rate + bracket.employee_fixed_amount
        )
        monthly_employer = _money(
            bracket.contribution_base * bracket.employer_rate
            + bracket.employer_fixed_amount
            + bracket.employer_additional_fixed_amount
        )
        employee_period_amount = (
            _money(monthly_employee / monthly_cutoff_count)
            if cutoff_number_in_month < monthly_cutoff_count
            else _money(monthly_employee - prior_month_employee_contributions.get(program, Decimal(0)))
        )
        employer_period_amount = (
            _money(monthly_employer / monthly_cutoff_count)
            if cutoff_number_in_month < monthly_cutoff_count
            else _money(monthly_employer - prior_month_employer_contributions.get(program, Decimal(0)))
        )
        contribution_lines.append(
            ContributionLine(
                program_code=program,
                employee_amount=employee_period_amount,
                employer_amount=employer_period_amount,
            )
        )

    employee_contributions = _money(
        sum((line.employee_amount for line in contribution_lines), Decimal(0))
    )
    employer_contributions = _money(
        sum((line.employer_amount for line in contribution_lines), Decimal(0))
    )
    exempt_limit_remaining = max(
        Decimal(0),
        tax_schedule.tax_exempt_benefit_limit - prior_ytd_limited_exempt_benefits,
    )
    exempt_limited_exempt = min(limited_benefits, exempt_limit_remaining)
    taxable_benefit_total = taxable_benefits + (limited_benefits - exempt_limited_exempt)
    period_taxable_income = _money(
        max(
            Decimal(0),
            gross_amount + taxable_benefit_total - employee_contributions,
        )
    )
    cumulative_tax_due = _tax_due(
        prior_ytd_taxable_income + period_taxable_income,
        tax_brackets,
    )
    if cumulative_tax_due is None:
        return NetPayCalculation(
            status="HOLD",
            hold_reason="No withholding-tax bracket covers year-to-date taxable income.",
            cash_benefit_amount=_money(cash_benefits),
            non_cash_benefit_amount=_money(non_cash_benefits),
            employee_benefit_deductions=_money(employee_benefit_deductions),
            exempt_limited_benefit_amount=_money(limited_benefits),
            taxable_income=period_taxable_income,
            employee_contributions=employee_contributions,
            employer_contributions=employer_contributions,
            withholding_tax=None,
            net_amount=None,
            contribution_lines=tuple(contribution_lines),
            benefit_lines=benefit_lines,
        )
    withholding_tax = _money(max(Decimal(0), cumulative_tax_due - prior_ytd_withholding_tax))
    net_amount = _money(
        gross_amount + cash_benefits - employee_contributions
        - employee_benefit_deductions - withholding_tax
    )
    if net_amount < 0:
        return NetPayCalculation(
            status="HOLD",
            hold_reason="Deductions exceed cash pay for this cutoff.",
            cash_benefit_amount=_money(cash_benefits),
            non_cash_benefit_amount=_money(non_cash_benefits),
            employee_benefit_deductions=_money(employee_benefit_deductions),
            exempt_limited_benefit_amount=_money(limited_benefits),
            taxable_income=period_taxable_income,
            employee_contributions=employee_contributions,
            employer_contributions=employer_contributions,
            withholding_tax=withholding_tax,
            net_amount=None,
            contribution_lines=tuple(contribution_lines),
            benefit_lines=benefit_lines,
        )
    return NetPayCalculation(
        status="READY",
        hold_reason=None,
        cash_benefit_amount=_money(cash_benefits),
        non_cash_benefit_amount=_money(non_cash_benefits),
        employee_benefit_deductions=_money(employee_benefit_deductions),
        exempt_limited_benefit_amount=_money(exempt_limited_exempt),
        taxable_income=period_taxable_income,
        employee_contributions=employee_contributions,
        employer_contributions=employer_contributions,
        withholding_tax=withholding_tax,
        net_amount=net_amount,
        contribution_lines=tuple(contribution_lines),
        benefit_lines=benefit_lines,
    )
