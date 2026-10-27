"""Withholding for payments made outside a regular payroll cutoff.

Regular (PAY_PERIOD) payments withhold only the incremental annual tax the
payment adds on top of year-to-date taxable income. 13th-month payouts use the
cumulative method: annual tax on year-to-date taxable income plus the payout,
minus all tax already withheld. This also collects tax on earlier YEAR_END
incentives that were paid without withholding. The final December cutoff
still reconciles the full year.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from app.payroll.domain.entities.benefits import (
    BenefitTaxTreatment,
    BenefitWithholdingTiming,
)
from app.payroll.domain.entities.off_cycle import validate_off_cycle_amount
from app.payroll.domain.entities.statutory_schedules import WithholdingTaxBracket
from app.payroll.domain.services.net_payroll import (
    SEMI_MONTHLY_PERIODS_PER_YEAR,
    _tax_due,
)


MONEY_QUANTUM = Decimal("0.01")
TaxCalculationBasis = Literal["ANNUAL_YTD", "SEMI_MONTHLY"]
OffCycleWithholdingMethod = Literal["INCREMENTAL", "CUMULATIVE"]


@dataclass(frozen=True)
class OffCycleYtd:
    taxable_income: Decimal
    withholding_tax: Decimal
    exempt_limited_benefits: Decimal


@dataclass(frozen=True)
class OffCycleTaxContext:
    calculation_basis: TaxCalculationBasis
    brackets: tuple[WithholdingTaxBracket, ...]
    tax_exempt_benefit_limit: Decimal


@dataclass(frozen=True)
class OffCycleLineAmounts:
    amount: Decimal
    taxable_amount: Decimal
    exempt_limited_amount: Decimal
    withholding_tax: Decimal
    net_amount: Decimal


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def annual_tax(
    annual_taxable_income: Decimal,
    *,
    calculation_basis: TaxCalculationBasis,
    brackets: tuple[WithholdingTaxBracket, ...],
) -> Decimal:
    income = max(Decimal(0), annual_taxable_income)
    if calculation_basis == "SEMI_MONTHLY":
        per_period = _tax_due(income / SEMI_MONTHLY_PERIODS_PER_YEAR, brackets)
        tax = None if per_period is None else _money(per_period * SEMI_MONTHLY_PERIODS_PER_YEAR)
    else:
        tax = _tax_due(income, brackets)
    if tax is None:
        raise ValueError(
            "No withholding-tax bracket covers this employee's year-to-date taxable income."
        )
    return tax


def split_taxable_amount(
    amount: Decimal,
    *,
    tax_treatment: BenefitTaxTreatment,
    tax_exempt_benefit_limit: Decimal,
    prior_exempt_limited_benefits: Decimal,
) -> tuple[Decimal, Decimal]:
    """Return (taxable_amount, exempt_limited_amount)."""
    if tax_treatment == "EXEMPT":
        return Decimal("0.00"), Decimal("0.00")
    if tax_treatment == "TAXABLE":
        return _money(amount), Decimal("0.00")
    remaining = max(Decimal(0), tax_exempt_benefit_limit - prior_exempt_limited_benefits)
    exempt = _money(min(amount, remaining))
    return _money(amount - exempt), exempt


def calculate_off_cycle_withholding(
    *,
    taxable_amount: Decimal,
    withholding_timing: BenefitWithholdingTiming,
    method: OffCycleWithholdingMethod,
    ytd: OffCycleYtd,
    tax: OffCycleTaxContext,
) -> Decimal:
    if withholding_timing == "YEAR_END":
        return Decimal("0.00")
    tax_with_payment = annual_tax(
        ytd.taxable_income + taxable_amount,
        calculation_basis=tax.calculation_basis,
        brackets=tax.brackets,
    )
    if method == "CUMULATIVE":
        return _money(max(Decimal(0), tax_with_payment - ytd.withholding_tax))
    if taxable_amount <= 0:
        return Decimal("0.00")
    tax_without_payment = annual_tax(
        ytd.taxable_income,
        calculation_basis=tax.calculation_basis,
        brackets=tax.brackets,
    )
    return _money(max(Decimal(0), tax_with_payment - tax_without_payment))


def calculate_off_cycle_line(
    *,
    amount: Decimal,
    tax_treatment: BenefitTaxTreatment,
    withholding_timing: BenefitWithholdingTiming,
    ytd: OffCycleYtd,
    tax: OffCycleTaxContext,
    method: OffCycleWithholdingMethod = "INCREMENTAL",
    fixed_split: tuple[Decimal, Decimal] | None = None,
) -> OffCycleLineAmounts:
    """Compute one employee's off-cycle amounts.

    ``fixed_split`` supplies (taxable, exempt) amounts already determined by
    another calculation, such as a 13th-month run.
    """
    validate_off_cycle_amount(amount)
    if fixed_split is not None:
        taxable_amount, exempt_limited_amount = (_money(value) for value in fixed_split)
        if taxable_amount < 0 or exempt_limited_amount < 0:
            raise ValueError("Taxable and exempt amounts cannot be negative.")
        if taxable_amount + exempt_limited_amount > _money(amount):
            raise ValueError("Taxable and exempt amounts cannot exceed the payment amount.")
    else:
        taxable_amount, exempt_limited_amount = split_taxable_amount(
            amount,
            tax_treatment=tax_treatment,
            tax_exempt_benefit_limit=tax.tax_exempt_benefit_limit,
            prior_exempt_limited_benefits=ytd.exempt_limited_benefits,
        )
    withholding_tax = min(
        _money(amount),
        calculate_off_cycle_withholding(
            taxable_amount=taxable_amount,
            withholding_timing=withholding_timing,
            method=method,
            ytd=ytd,
            tax=tax,
        ),
    )
    return OffCycleLineAmounts(
        amount=_money(amount),
        taxable_amount=taxable_amount,
        exempt_limited_amount=exempt_limited_amount,
        withholding_tax=withholding_tax,
        net_amount=_money(amount - withholding_tax),
    )
