import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.payroll.domain.entities.benefits import CutoffBenefit
from app.payroll.domain.entities.statutory_schedules import (
    ContributionBracket,
    WithholdingTaxBracket,
    WithholdingTaxSchedule,
)
from app.payroll.domain.services.net_payroll import calculate_net_pay


class NetPayrollTests(unittest.TestCase):
    def setUp(self) -> None:
        self.programs = ("SSS", "PHILHEALTH", "PAGIBIG")
        self.brackets = {
            program: (
                ContributionBracket(
                    id=uuid4(),
                    schedule_id=uuid4(),
                    bracket_number=1,
                    compensation_min=Decimal("0"),
                    compensation_max=None,
                    contribution_base=Decimal("10000"),
                    employee_rate=Decimal("0.05"),
                    employer_rate=Decimal("0.07"),
                    employee_fixed_amount=Decimal("1"),
                    employer_fixed_amount=Decimal("2"),
                    employer_additional_fixed_amount=Decimal("3"),
                ),
            )
            for program in self.programs
        }
        self.tax_schedule = WithholdingTaxSchedule(
            id=uuid4(),
            schedule_name="Tax schedule",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            tax_exempt_benefit_limit=Decimal("500"),
            source_reference="official circular",
            status="ACTIVE",
            created_at=datetime.now(timezone.utc),
            created_by=None,
            updated_at=datetime.now(timezone.utc),
            updated_by=None,
            row_version=1,
        )
        self.tax_brackets = (
            WithholdingTaxBracket(
                id=uuid4(),
                schedule_id=self.tax_schedule.id,
                bracket_number=1,
                annual_income_min=Decimal("0"),
                annual_income_max=None,
                base_tax=Decimal("0"),
                marginal_rate=Decimal("0.10"),
                excess_over=Decimal("0"),
            ),
        )

    def calculate(self, **overrides):
        values = {
            "gross_amount": Decimal("2000"),
            "benefits": (),
            "monthly_compensation": Decimal("10000"),
            "contribution_brackets": self.brackets,
            "tax_schedule": self.tax_schedule,
            "tax_brackets": self.tax_brackets,
            "monthly_cutoff_count": 2,
            "cutoff_number_in_month": 1,
            "prior_month_employee_contributions": {},
            "prior_month_employer_contributions": {},
            "prior_ytd_taxable_income": Decimal(0),
            "prior_ytd_withholding_tax": Decimal(0),
            "prior_ytd_limited_exempt_benefits": Decimal(0),
        }
        values.update(overrides)
        return calculate_net_pay(**values)

    def benefit(self, category, treatment, amount):
        return CutoffBenefit(
            id=uuid4(),
            cutoff_id=uuid4(),
            employee_id=uuid4(),
            benefit_type_id=uuid4(),
            benefit_code="BENEFIT",
            benefit_name="Benefit",
            category=category,
            tax_treatment=treatment,
            amount=Decimal(amount),
            notes=None,
        )

    def test_holds_net_pay_if_required_statutory_schedules_are_missing(self) -> None:
        result = self.calculate(
            contribution_brackets={"SSS": self.brackets["SSS"]},
            tax_schedule=None,
        )

        self.assertEqual(result.status, "HOLD")
        self.assertIsNone(result.net_amount)
        self.assertIn("PHILHEALTH", result.hold_reason or "")
        self.assertIn("WITHHOLDING_TAX", result.hold_reason or "")

    def test_holds_if_tax_year_opening_balance_was_not_entered(self) -> None:
        result = self.calculate(opening_ytd_balance_missing=True)

        self.assertEqual(result.status, "HOLD")
        self.assertIsNone(result.net_amount)
        self.assertIn("opening balance must be recorded", result.hold_reason or "")

    def test_calculates_taxable_and_cash_benefits_and_employee_deductions(self) -> None:
        result = self.calculate(
            benefits=(
                self.benefit("CASH_ALLOWANCE", "TAXABLE", "100"),
                self.benefit("ONE_TIME_BONUS", "TAXABLE", "10"),
                self.benefit("REIMBURSEMENT", "EXEMPT", "10"),
                self.benefit("EMPLOYER_PAID_INSURANCE", "EXEMPT", "20"),
                self.benefit("EMPLOYEE_DEDUCTION", "EXEMPT", "25"),
                self.benefit("NON_CASH", "EXEMPT_LIMITED", "600"),
            )
        )

        self.assertEqual(result.status, "READY")
        self.assertEqual(result.cash_benefit_amount, Decimal("120.00"))
        self.assertEqual(result.non_cash_benefit_amount, Decimal("620.00"))
        self.assertEqual(result.employee_benefit_deductions, Decimal("25.00"))
        self.assertEqual(result.exempt_limited_benefit_amount, Decimal("500.00"))
        self.assertEqual(result.taxable_income, Decimal("1458.50"))
        self.assertEqual(result.employee_contributions, Decimal("751.50"))
        self.assertEqual(result.employer_contributions, Decimal("1057.50"))
        self.assertEqual(result.withholding_tax, Decimal("145.85"))
        self.assertEqual(result.net_amount, Decimal("1197.65"))
        self.assertEqual(len(result.benefit_lines), 6)

    def test_attendance_benefit_prorates_and_applies_late_and_undertime_rates(self) -> None:
        result = self.calculate(
            benefits=(
                replace(
                    self.benefit("CASH_ALLOWANCE", "TAXABLE", "600"),
                    attendance_based=True,
                    deduct_for_late=True,
                    deduct_for_undertime=True,
                ),
            ),
            scheduled_days=Decimal("10"),
            paid_days=Decimal("8"),
            required_work_minutes=4800,
            late_minutes=20,
            undertime_minutes=10,
        )

        self.assertEqual(result.cash_benefit_amount, Decimal("476.25"))
        self.assertEqual(result.benefit_lines[0].amount, Decimal("476.25"))
        self.assertEqual(result.taxable_income, Decimal("1724.75"))

    def test_attendance_benefit_deductions_use_schedule_minutes_and_selected_flags(self) -> None:
        benefit = replace(
            self.benefit("CASH_ALLOWANCE", "TAXABLE", "900"),
            attendance_based=True,
            deduct_for_late=True,
            deduct_for_undertime=False,
        )
        result = self.calculate(
            benefits=(benefit,),
            scheduled_days=Decimal("5"),
            paid_days=Decimal("5"),
            required_work_minutes=2100,
            late_minutes=70,
            undertime_minutes=50,
        )

        self.assertEqual(result.benefit_lines[0].amount, Decimal("870.00"))

    def test_attendance_benefit_deduction_requires_schedule_minutes(self) -> None:
        benefit = replace(
            self.benefit("CASH_ALLOWANCE", "TAXABLE", "900"),
            attendance_based=True,
            deduct_for_late=True,
        )

        with self.assertRaisesRegex(ValueError, "Required scheduled work minutes are missing"):
            self.calculate(
                benefits=(benefit,),
                scheduled_days=Decimal("5"),
                paid_days=Decimal("5"),
                late_minutes=1,
            )

    def test_final_cutoff_reconciles_monthly_contribution_rounding(self) -> None:
        small_fixed_bracket = ContributionBracket(
            id=uuid4(),
            schedule_id=uuid4(),
            bracket_number=1,
            compensation_min=Decimal("0"),
            compensation_max=None,
            contribution_base=Decimal("0"),
            employee_rate=Decimal("0"),
            employer_rate=Decimal("0"),
            employee_fixed_amount=Decimal("0.05"),
            employer_fixed_amount=Decimal("0.05"),
            employer_additional_fixed_amount=Decimal("0"),
        )
        result = self.calculate(
            monthly_cutoff_count=2,
            cutoff_number_in_month=2,
            contribution_brackets={
                **self.brackets,
                "SSS": (small_fixed_bracket,),
            },
            prior_month_employee_contributions={"SSS": Decimal("0.03")},
            prior_month_employer_contributions={"SSS": Decimal("0.03")},
        )

        self.assertEqual(result.contribution_lines[0].employee_amount, Decimal("0.02"))
        self.assertEqual(result.contribution_lines[0].employer_amount, Decimal("0.02"))

    def test_tax_withholding_uses_opening_ytd_and_limited_benefit_usage(self) -> None:
        limited_benefit = self.benefit("NON_CASH", "EXEMPT_LIMITED", "600")
        result = self.calculate(
            benefits=(limited_benefit,),
            prior_ytd_taxable_income=Decimal("1000"),
            prior_ytd_withholding_tax=Decimal("100"),
            prior_ytd_limited_exempt_benefits=Decimal("400"),
        )

        self.assertEqual(result.status, "READY")
        self.assertEqual(result.exempt_limited_benefit_amount, Decimal("100.00"))
        self.assertEqual(result.taxable_income, Decimal("1748.50"))
        self.assertEqual(result.withholding_tax, Decimal("174.85"))
        self.assertEqual(result.benefit_lines[0].amount, Decimal("600.00"))


if __name__ == "__main__":
    unittest.main()
