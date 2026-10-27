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
SEMI_MONTHLY_PERIODS_PER_YEAR = Decimal(24)
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
    contribution_timing: Literal["PER_CUTOFF", "FINAL_CUTOFF"] = "PER_CUTOFF",
    prior_month_employee_contributions: dict[ContributionProgram, Decimal],
    prior_month_employer_contributions: dict[ContributionProgram, Decimal],
    prior_ytd_taxable_income: Decimal,
    prior_ytd_withholding_tax: Decimal,
    prior_ytd_limited_exempt_benefits: Decimal,
    pay_frequency: Literal["WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY"] = "SEMIMONTHLY",
    cutoff_half: Literal["FIRST_HALF", "SECOND_HALF"] | None = None,
    semimonthly_compensation: Decimal | None = None,
    year_end_wtax_reconciliation_enabled: bool = False,
    is_final_december_cutoff: bool = False,
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
            withholding_timing=benefit.withholding_timing,
            loan_id=benefit.loan_id,
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
    year_end_taxable_bonuses = sum(
        (
            benefit.amount
            for benefit in calculated_benefits
            if benefit.tax_treatment == "TAXABLE"
            and benefit.withholding_timing == "YEAR_END"
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
    if opening_ytd_balance_missing and (
        tax_schedule.calculation_basis == "ANNUAL_YTD"
        or tax_schedule.tax_exempt_benefit_limit > 0
    ):
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
    if year_end_taxable_bonuses and (
        not year_end_wtax_reconciliation_enabled
        or tax_schedule.calculation_basis != "SEMI_MONTHLY"
    ):
        return NetPayCalculation(
            status="HOLD",
            hold_reason=(
                "Year-end-taxable bonuses require year-end WTAX reconciliation "
                "enabled and an active semi-monthly withholding-tax schedule."
            ),
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

    if cutoff_half is None and (
        contribution_timing == "FINAL_CUTOFF" or pay_frequency == "SEMIMONTHLY"
    ):
        return NetPayCalculation(
            status="HOLD",
            hold_reason=(
                "The cutoff must be designated First Half or Second Half before "
                "statutory contributions can be calculated."
            ),
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

    periods_per_year = {
        "WEEKLY": Decimal(52),
        "BIWEEKLY": Decimal(26),
        "SEMIMONTHLY": Decimal(24),
        "MONTHLY": Decimal(12),
    }[pay_frequency]
    periods_per_month = periods_per_year / Decimal(12)
    use_half_month_basis = (
        contribution_timing == "PER_CUTOFF"
        and pay_frequency == "SEMIMONTHLY"
        and cutoff_half == "FIRST_HALF"
    )
    contribution_compensation = monthly_compensation
    if use_half_month_basis:
        contribution_compensation = (
            semimonthly_compensation
            if semimonthly_compensation is not None
            else _money(monthly_compensation / Decimal(2))
        )

    contribution_lines: list[ContributionLine] = []
    for program in REQUIRED_CONTRIBUTION_PROGRAMS:
        bracket = _amount_in_bracket(contribution_compensation, contribution_brackets[program])
        if bracket is None:
            return NetPayCalculation(
                status="HOLD",
                hold_reason=f"No {program} contribution bracket covers the contribution compensation basis.",
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
        bracket_employee = _money(
            (
                contribution_compensation * bracket.employee_rate
                if program == "PAGIBIG"
                else bracket.contribution_base * bracket.employee_rate
            ) + bracket.employee_fixed_amount
        )
        bracket_employer = _money(
            (
                contribution_compensation * bracket.employer_rate
                if program == "PAGIBIG"
                else bracket.contribution_base * bracket.employer_rate
            )
            + bracket.employer_fixed_amount
            + bracket.employer_additional_fixed_amount
        )
        if program == "PAGIBIG":
            if (
                bracket.employee_contribution_cap is None
                or bracket.employer_contribution_cap is None
            ):
                return NetPayCalculation(
                    status="HOLD",
                    hold_reason="Pag-IBIG brackets require monthly employee and employer contribution caps.",
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
            bracket_employee = min(bracket_employee, bracket.employee_contribution_cap)
            bracket_employer = min(bracket_employer, bracket.employer_contribution_cap)
        if contribution_timing == "FINAL_CUTOFF":
            employee_period_amount = (
                bracket_employee
                if cutoff_half == "SECOND_HALF"
                else Decimal("0.00")
            )
            employer_period_amount = (
                bracket_employer
                if cutoff_half == "SECOND_HALF"
                else Decimal("0.00")
            )
        elif pay_frequency == "SEMIMONTHLY":
            employee_period_amount = bracket_employee
            employer_period_amount = bracket_employer
            if cutoff_half == "SECOND_HALF":
                employee_period_amount = _money(
                    bracket_employee - prior_month_employee_contributions.get(program, Decimal(0))
                )
                employer_period_amount = _money(
                    bracket_employer - prior_month_employer_contributions.get(program, Decimal(0))
                )
            if employee_period_amount < 0 or employer_period_amount < 0:
                return NetPayCalculation(
                    status="HOLD",
                    hold_reason=(
                        f"Saved First Half {program} contributions exceed the monthly "
                        "contribution. Review and recalculate First Half payroll."
                    ),
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
        else:
            employee_period_amount = _money(bracket_employee / periods_per_month)
            employer_period_amount = _money(bracket_employer / periods_per_month)
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
    withholding_period_taxable_income = _money(
        max(
            Decimal(0),
            gross_amount
            + taxable_benefit_total
            - year_end_taxable_bonuses
            - employee_contributions,
        )
    )
    is_year_end_reconciliation = (
        tax_schedule.calculation_basis == "SEMI_MONTHLY"
        and year_end_wtax_reconciliation_enabled
        and is_final_december_cutoff
    )
    if is_year_end_reconciliation:
        annual_taxable_income = prior_ytd_taxable_income + period_taxable_income
        tax_per_semi_monthly_period = _tax_due(
            annual_taxable_income / SEMI_MONTHLY_PERIODS_PER_YEAR,
            tax_brackets,
        )
        tax_due = (
            _money(tax_per_semi_monthly_period * SEMI_MONTHLY_PERIODS_PER_YEAR)
            if tax_per_semi_monthly_period is not None
            else None
        )
    else:
        tax_due = _tax_due(
            withholding_period_taxable_income
            if tax_schedule.calculation_basis == "SEMI_MONTHLY"
            else prior_ytd_taxable_income + period_taxable_income,
            tax_brackets,
        )
    if tax_due is None:
        if is_year_end_reconciliation:
            tax_bracket_error = (
                "No withholding-tax bracket covers annualized taxable income for the year-end reconciliation."
            )
        elif tax_schedule.calculation_basis == "SEMI_MONTHLY":
            tax_bracket_error = "No withholding-tax bracket covers this payroll period's taxable income."
        else:
            tax_bracket_error = "No withholding-tax bracket covers year-to-date taxable income."
        return NetPayCalculation(
            status="HOLD",
            hold_reason=tax_bracket_error,
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
    withholding_tax = _money(
        tax_due - prior_ytd_withholding_tax
        if is_year_end_reconciliation
        else tax_due
        if tax_schedule.calculation_basis == "SEMI_MONTHLY"
        else max(Decimal(0), tax_due - prior_ytd_withholding_tax)
    )
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
