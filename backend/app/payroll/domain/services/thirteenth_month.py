from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class ThirteenthMonthAmounts:
    basic_salary_earned: Decimal
    thirteenth_month_pay: Decimal
    tax_exempt_amount: Decimal
    taxable_amount: Decimal


def calculate_thirteenth_month_amounts(
    *,
    basic_salary_earned: Decimal,
    annual_benefit_exemption_limit: Decimal,
    prior_ytd_exempt_benefits: Decimal,
) -> ThirteenthMonthAmounts:
    amounts = (
        basic_salary_earned,
        annual_benefit_exemption_limit,
        prior_ytd_exempt_benefits,
    )
    if any(not value.is_finite() or value < 0 for value in amounts):
        raise ValueError("13th-month salary and tax-exemption amounts must be finite and nonnegative.")

    rounded_basic_salary = basic_salary_earned.quantize(
        MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )
    thirteenth_month_pay = (rounded_basic_salary / Decimal(12)).quantize(
        MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )
    remaining_exemption = max(
        Decimal(0),
        annual_benefit_exemption_limit - prior_ytd_exempt_benefits,
    )
    tax_exempt_amount = min(thirteenth_month_pay, remaining_exemption)
    return ThirteenthMonthAmounts(
        basic_salary_earned=rounded_basic_salary,
        thirteenth_month_pay=thirteenth_month_pay,
        tax_exempt_amount=tax_exempt_amount,
        taxable_amount=thirteenth_month_pay - tax_exempt_amount,
    )
