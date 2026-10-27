import unittest
from decimal import Decimal

from app.payroll.domain.services.thirteenth_month import (
    calculate_thirteenth_month_amounts,
)


class ThirteenthMonthCalculationTests(unittest.TestCase):
    def test_divides_eligible_basic_salary_by_twelve(self) -> None:
        result = calculate_thirteenth_month_amounts(
            basic_salary_earned=Decimal("360000"),
            annual_benefit_exemption_limit=Decimal("90000"),
            prior_ytd_exempt_benefits=Decimal(0),
        )

        self.assertEqual(result.basic_salary_earned, Decimal("360000.00"))
        self.assertEqual(result.thirteenth_month_pay, Decimal("30000.00"))
        self.assertEqual(result.tax_exempt_amount, Decimal("30000.00"))
        self.assertEqual(result.taxable_amount, Decimal("0.00"))

    def test_applies_remaining_shared_benefit_exemption_and_taxable_excess(self) -> None:
        result = calculate_thirteenth_month_amounts(
            basic_salary_earned=Decimal("1200000"),
            annual_benefit_exemption_limit=Decimal("90000"),
            prior_ytd_exempt_benefits=Decimal("70000"),
        )

        self.assertEqual(result.thirteenth_month_pay, Decimal("100000.00"))
        self.assertEqual(result.tax_exempt_amount, Decimal("20000.00"))
        self.assertEqual(result.taxable_amount, Decimal("80000.00"))

    def test_rounds_pay_to_cents(self) -> None:
        result = calculate_thirteenth_month_amounts(
            basic_salary_earned=Decimal("1000"),
            annual_benefit_exemption_limit=Decimal("90000"),
            prior_ytd_exempt_benefits=Decimal(0),
        )

        self.assertEqual(result.thirteenth_month_pay, Decimal("83.33"))

    def test_rejects_negative_salary_or_exemption_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite and nonnegative"):
            calculate_thirteenth_month_amounts(
                basic_salary_earned=Decimal("-1"),
                annual_benefit_exemption_limit=Decimal("90000"),
                prior_ytd_exempt_benefits=Decimal(0),
            )


if __name__ == "__main__":
    unittest.main()
