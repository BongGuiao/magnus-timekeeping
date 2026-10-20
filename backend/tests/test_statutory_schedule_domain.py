import unittest
from datetime import date
from decimal import Decimal

from app.payroll.domain.entities.statutory_schedules import (
    validate_complete_bracket_ranges,
    validate_contribution_bracket_values,
    validate_schedule_values,
    validate_withholding_tax_bracket_values,
)


class StatutoryScheduleDomainTests(unittest.TestCase):
    def test_accepts_complete_contiguous_brackets(self) -> None:
        validate_complete_bracket_ranges(
            [
                (1, Decimal("0.00"), Decimal("10000.00")),
                (2, Decimal("10000.01"), None),
            ]
        )

    def test_rejects_bracket_gap(self) -> None:
        with self.assertRaisesRegex(ValueError, "cover each amount exactly once"):
            validate_complete_bracket_ranges(
                [
                    (1, Decimal("0.00"), Decimal("10000.00")),
                    (2, Decimal("10000.02"), None),
                ]
            )

    def test_rejects_open_ended_nonterminal_bracket(self) -> None:
        with self.assertRaisesRegex(ValueError, "Only the final bracket"):
            validate_complete_bracket_ranges(
                [
                    (1, Decimal("0.00"), None),
                    (2, Decimal("10000.00"), None),
                ]
            )

    def test_rejects_nonsequential_bracket_numbers(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be sequential"):
            validate_complete_bracket_ranges(
                [
                    (2, Decimal("0.00"), Decimal("10000.00")),
                    (3, Decimal("10000.01"), None),
                ]
            )

    def test_rejects_tax_schedule_with_end_before_start(self) -> None:
        with self.assertRaisesRegex(ValueError, "on or after"):
            validate_schedule_values(
                schedule_name="Annual tax table",
                effective_from=date(2026, 1, 1),
                effective_to=date(2025, 12, 31),
                source_reference="Official source",
            )

    def test_rejects_contribution_rate_over_one(self) -> None:
        with self.assertRaisesRegex(ValueError, "between zero and one"):
            validate_contribution_bracket_values(
                bracket_number=1,
                compensation_min=Decimal("0"),
                compensation_max=None,
                contribution_base=Decimal("0"),
                employee_rate=Decimal("1.01"),
                employer_rate=Decimal("0"),
                employee_fixed_amount=Decimal("0"),
                employer_fixed_amount=Decimal("0"),
                employer_additional_fixed_amount=Decimal("0"),
            )

    def test_rejects_negative_withholding_tax_amount(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            validate_withholding_tax_bracket_values(
                bracket_number=1,
                annual_income_min=Decimal("0"),
                annual_income_max=None,
                base_tax=Decimal("-1"),
                marginal_rate=Decimal("0"),
                excess_over=Decimal("0"),
            )


if __name__ == "__main__":
    unittest.main()
