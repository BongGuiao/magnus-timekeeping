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
                    employee_contribution_cap=Decimal("1000") if program == "PAGIBIG" else None,
                    employer_contribution_cap=Decimal("1000") if program == "PAGIBIG" else None,
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
            "cutoff_half": "FIRST_HALF",
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
        self.assertEqual(result.taxable_income, Decimal("957.00"))
        self.assertEqual(result.employee_contributions, Decimal("1253.00"))
        self.assertEqual(result.employer_contributions, Decimal("1765.00"))
        self.assertEqual(result.withholding_tax, Decimal("95.70"))
        self.assertEqual(result.net_amount, Decimal("746.30"))
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
        self.assertEqual(result.taxable_income, Decimal("1223.25"))

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

    def test_every_cutoff_reconciles_monthly_contribution_rounding(self) -> None:
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
            cutoff_half="SECOND_HALF",
            prior_month_employee_contributions={"SSS": Decimal("0.03")},
            prior_month_employer_contributions={"SSS": Decimal("0.03")},
        )

        self.assertEqual(result.contribution_lines[0].employee_amount, Decimal("0.02"))
        self.assertEqual(result.contribution_lines[0].employer_amount, Decimal("0.02"))

    def test_final_cutoff_timing_defers_monthly_contributions_until_second_half(self) -> None:
        first_cutoff = self.calculate(
            contribution_timing="FINAL_CUTOFF",
            cutoff_half="FIRST_HALF",
        )
        self.assertTrue(
            all(
                line.employee_amount == Decimal("0.00")
                and line.employer_amount == Decimal("0.00")
                for line in first_cutoff.contribution_lines
            )
        )

        final_cutoff = self.calculate(
            contribution_timing="FINAL_CUTOFF",
            cutoff_half="SECOND_HALF",
            prior_month_employee_contributions={program: Decimal("99") for program in self.programs},
            prior_month_employer_contributions={program: Decimal("199") for program in self.programs},
        )
        self.assertTrue(
            all(
                line.employee_amount == Decimal("501.00")
                and line.employer_amount == Decimal("705.00")
                for line in final_cutoff.contribution_lines
            )
        )

    def test_every_cutoff_uses_half_month_bracket_then_reconciles_monthly_total(self) -> None:
        brackets = {
            program: (
                replace(
                    self.brackets[program][0],
                    compensation_max=Decimal("5000"),
                    contribution_base=Decimal("5000"),
                ),
                replace(
                    self.brackets[program][0],
                    bracket_number=2,
                    compensation_min=Decimal("5000.01"),
                ),
            )
            for program in self.programs
        }
        first_half = self.calculate(
            contribution_timing="PER_CUTOFF",
            cutoff_half="FIRST_HALF",
            contribution_brackets=brackets,
            prior_month_employee_contributions={program: Decimal("999") for program in self.programs},
            prior_month_employer_contributions={program: Decimal("999") for program in self.programs},
        )
        second_half = self.calculate(
            contribution_timing="PER_CUTOFF",
            cutoff_half="SECOND_HALF",
            contribution_brackets=brackets,
            prior_month_employee_contributions={
                line.program_code: line.employee_amount for line in first_half.contribution_lines
            },
            prior_month_employer_contributions={
                line.program_code: line.employer_amount for line in first_half.contribution_lines
            },
        )

        self.assertEqual(first_half.status, "READY")
        self.assertEqual(second_half.status, "READY")
        self.assertEqual(len(first_half.contribution_lines), 3)
        for first_line, second_line in zip(
            first_half.contribution_lines,
            second_half.contribution_lines,
        ):
            self.assertEqual(first_line.employee_amount, Decimal("251.00"))
            self.assertEqual(second_line.employee_amount, Decimal("250.00"))
            self.assertEqual(first_line.employer_amount, Decimal("355.00"))
            self.assertEqual(second_line.employer_amount, Decimal("350.00"))

    def test_final_cutoff_timing_requires_cutoff_half_designation(self) -> None:
        result = self.calculate(contribution_timing="FINAL_CUTOFF", cutoff_half=None)

        self.assertEqual(result.status, "HOLD")
        self.assertIn("designated First Half or Second Half", result.hold_reason or "")

    def test_every_cutoff_timing_requires_semimonthly_cutoff_half(self) -> None:
        result = self.calculate(cutoff_half=None)

        self.assertEqual(result.status, "HOLD")
        self.assertIn("designated First Half or Second Half", result.hold_reason or "")

    def test_second_half_without_saved_first_half_collects_monthly_total(self) -> None:
        result = self.calculate(cutoff_half="SECOND_HALF")

        self.assertEqual(result.status, "READY")
        self.assertEqual(len(result.contribution_lines), 3)
        for line in result.contribution_lines:
            self.assertEqual(line.employee_amount, Decimal("501.00"))
            self.assertEqual(line.employer_amount, Decimal("705.00"))

    def test_second_half_holds_if_saved_share_exceeds_monthly_contribution(self) -> None:
        for program in self.programs:
            for share in ("employee", "employer"):
                with self.subTest(program=program, share=share):
                    result = self.calculate(
                        cutoff_half="SECOND_HALF",
                        **{f"prior_month_{share}_contributions": {program: Decimal("9999")}},
                    )
                    self.assertEqual(result.status, "HOLD")
                    self.assertIsNone(result.net_amount)
                    self.assertIn(f"First Half {program}", result.hold_reason or "")

    def test_first_half_uses_bracket_fixed_amounts_without_halving_them(self) -> None:
        result = self.calculate()

        sss = result.contribution_lines[0]
        self.assertEqual(sss.employee_amount, Decimal("501.00"))
        self.assertEqual(sss.employer_amount, Decimal("705.00"))

    def test_no_cash_pay_still_holds_instead_of_waiving_contributions(self) -> None:
        for timing, half in (
            ("PER_CUTOFF", "FIRST_HALF"),
            ("PER_CUTOFF", "SECOND_HALF"),
            ("FINAL_CUTOFF", "SECOND_HALF"),
        ):
            with self.subTest(timing=timing, half=half):
                result = self.calculate(
                    gross_amount=Decimal(0),
                    contribution_timing=timing,
                    cutoff_half=half,
                    scheduled_days=Decimal("10"),
                    paid_days=Decimal(0),
                )
                self.assertEqual(result.status, "HOLD")
                self.assertEqual(result.hold_reason, "Deductions exceed cash pay for this cutoff.")
                self.assertIsNone(result.net_amount)
                self.assertGreater(result.employee_contributions, 0)

    def test_first_half_reports_missing_half_month_bracket(self) -> None:
        result = self.calculate(
            contribution_brackets={
                **self.brackets,
                "SSS": (replace(self.brackets["SSS"][0], compensation_min=Decimal("7500")),),
            },
        )
        self.assertEqual(result.status, "HOLD")
        self.assertIn("No SSS contribution bracket", result.hold_reason or "")

    def test_other_pay_frequencies_retain_period_allocation(self) -> None:
        for frequency, periods in (("MONTHLY", 12), ("WEEKLY", 52), ("BIWEEKLY", 26)):
            with self.subTest(frequency=frequency):
                result = self.calculate(
                    pay_frequency=frequency,
                    cutoff_half=None,
                    prior_month_employee_contributions={"SSS": Decimal("99")},
                )
                self.assertEqual(result.status, "READY")
                self.assertEqual(
                    result.contribution_lines[0].employee_amount,
                    (Decimal("501") * Decimal(12) / Decimal(periods)).quantize(Decimal("0.01")),
                )

    def test_every_cutoff_splits_daily_rate_sss_using_semimonthly_salary_basis(self) -> None:
        sss_bracket = replace(
            self.brackets["SSS"][0],
            compensation_min=Decimal("21750"),
            compensation_max=Decimal("22249.99"),
            contribution_base=Decimal("22000"),
            employee_rate=Decimal("0.05"),
            employee_fixed_amount=Decimal(0),
            employer_rate=Decimal("0.10"),
            employer_fixed_amount=Decimal(0),
            employer_additional_fixed_amount=Decimal(0),
        )
        result = self.calculate(
            monthly_compensation=Decimal("22170.83"),
            contribution_timing="PER_CUTOFF",
            contribution_brackets={
                **self.brackets,
                "SSS": (
                    replace(
                        sss_bracket,
                        compensation_min=Decimal("10750"),
                        compensation_max=Decimal("11249.99"),
                        contribution_base=Decimal("11000"),
                    ),
                    sss_bracket,
                ),
            },
        )

        sss = next(line for line in result.contribution_lines if line.program_code == "SSS")
        self.assertEqual(sss.employee_amount, Decimal("550.00"))

    def test_pagibig_caps_each_bracket_result_and_reconciles_monthly_cap(self) -> None:
        pagibig_bracket = replace(
            self.brackets["PAGIBIG"][0],
            employee_rate=Decimal("0.02"),
            employer_rate=Decimal("0.02"),
            employee_fixed_amount=Decimal(0),
            employer_fixed_amount=Decimal(0),
            employer_additional_fixed_amount=Decimal(0),
            employee_contribution_cap=Decimal("200"),
            employer_contribution_cap=Decimal("200"),
        )
        result = self.calculate(
            monthly_compensation=Decimal("20000"),
            contribution_brackets={
                **self.brackets,
                "PAGIBIG": (pagibig_bracket,),
            },
        )

        pagibig = next(line for line in result.contribution_lines if line.program_code == "PAGIBIG")
        self.assertEqual(pagibig.employee_amount, Decimal("200.00"))
        self.assertEqual(pagibig.employer_amount, Decimal("200.00"))
        second_half = self.calculate(
            monthly_compensation=Decimal("20000"),
            cutoff_half="SECOND_HALF",
            contribution_brackets={**self.brackets, "PAGIBIG": (pagibig_bracket,)},
            prior_month_employee_contributions={"PAGIBIG": pagibig.employee_amount},
            prior_month_employer_contributions={"PAGIBIG": pagibig.employer_amount},
        )
        second_pagibig = next(
            line for line in second_half.contribution_lines if line.program_code == "PAGIBIG"
        )
        self.assertEqual(second_pagibig.employee_amount, Decimal("0.00"))
        self.assertEqual(second_pagibig.employer_amount, Decimal("0.00"))

    def test_pagibig_uses_lower_employee_rate_at_salary_floor(self) -> None:
        lower_bracket = replace(
            self.brackets["PAGIBIG"][0],
            compensation_max=Decimal("1500"),
            employee_rate=Decimal("0.01"),
            employer_rate=Decimal("0.02"),
            employee_fixed_amount=Decimal(0),
            employer_fixed_amount=Decimal(0),
            employer_additional_fixed_amount=Decimal(0),
            employee_contribution_cap=Decimal("200"),
            employer_contribution_cap=Decimal("200"),
        )
        upper_bracket = replace(
            lower_bracket,
            id=uuid4(),
            bracket_number=2,
            compensation_min=Decimal("1500.01"),
            compensation_max=None,
            employee_rate=Decimal("0.02"),
        )
        result = self.calculate(
            monthly_compensation=Decimal("1500"),
            contribution_brackets={
                **self.brackets,
                "PAGIBIG": (lower_bracket, upper_bracket),
            },
        )

        pagibig = next(line for line in result.contribution_lines if line.program_code == "PAGIBIG")
        self.assertEqual(pagibig.employee_amount, Decimal("7.50"))
        self.assertEqual(pagibig.employer_amount, Decimal("15.00"))

    def test_semi_monthly_tax_uses_period_bracket_without_ytd_reconciliation(self) -> None:
        semi_monthly_schedule = replace(
            self.tax_schedule,
            calculation_basis="SEMI_MONTHLY",
        )
        result = self.calculate(
            tax_schedule=semi_monthly_schedule,
            prior_ytd_taxable_income=Decimal("100000"),
            prior_ytd_withholding_tax=Decimal("5000"),
        )

        self.assertEqual(result.status, "READY")
        self.assertEqual(result.withholding_tax, Decimal("74.70"))

    def test_semi_monthly_tax_is_calculated_for_each_payroll_cutoff(self) -> None:
        result = self.calculate(
            tax_schedule=replace(self.tax_schedule, calculation_basis="SEMI_MONTHLY"),
            monthly_cutoff_count=1,
        )

        self.assertEqual(result.status, "READY")
        self.assertEqual(result.withholding_tax, Decimal("74.70"))
        self.assertIsNotNone(result.net_amount)

    def test_year_end_bonus_is_taxable_but_not_withheld_in_its_pay_period(self) -> None:
        bonus = replace(
            self.benefit("ONE_TIME_BONUS", "TAXABLE", "1000"),
            withholding_timing="YEAR_END",
        )
        result = self.calculate(
            benefits=(bonus,),
            tax_schedule=replace(self.tax_schedule, calculation_basis="SEMI_MONTHLY"),
            year_end_wtax_reconciliation_enabled=True,
        )
        regular_result = self.calculate(
            tax_schedule=replace(self.tax_schedule, calculation_basis="SEMI_MONTHLY"),
        )

        self.assertEqual(result.status, "READY")
        self.assertEqual(result.taxable_income, regular_result.taxable_income + Decimal("1000.00"))
        self.assertEqual(result.withholding_tax, regular_result.withholding_tax)

    def test_year_end_bonus_requires_reconciliation_setting_and_semi_monthly_schedule(self) -> None:
        bonus = replace(
            self.benefit("ONE_TIME_BONUS", "TAXABLE", "1000"),
            withholding_timing="YEAR_END",
        )
        result = self.calculate(
            benefits=(bonus,),
            tax_schedule=replace(self.tax_schedule, calculation_basis="SEMI_MONTHLY"),
        )

        self.assertEqual(result.status, "HOLD")
        self.assertIn("year-end WTAX reconciliation enabled", result.hold_reason or "")

    def test_year_end_reconciliation_includes_deferred_bonus(self) -> None:
        bonus = replace(
            self.benefit("ONE_TIME_BONUS", "TAXABLE", "1000"),
            withholding_timing="YEAR_END",
        )
        result = self.calculate(
            benefits=(bonus,),
            tax_schedule=replace(self.tax_schedule, calculation_basis="SEMI_MONTHLY"),
            prior_ytd_taxable_income=Decimal("100000"),
            prior_ytd_withholding_tax=Decimal("10000"),
            year_end_wtax_reconciliation_enabled=True,
            is_final_december_cutoff=True,
        )

        self.assertEqual(result.status, "READY")
        self.assertEqual(result.taxable_income, Decimal("1747.00"))
        self.assertEqual(result.withholding_tax, Decimal("174.80"))

    def test_year_end_reconciliation_refunds_overwithheld_tax_on_final_december_cutoff(self) -> None:
        result = self.calculate(
            tax_schedule=replace(self.tax_schedule, calculation_basis="SEMI_MONTHLY"),
            prior_ytd_taxable_income=Decimal("200000"),
            prior_ytd_withholding_tax=Decimal("25000"),
            year_end_wtax_reconciliation_enabled=True,
            is_final_december_cutoff=True,
        )

        self.assertEqual(result.status, "READY")
        self.assertEqual(result.withholding_tax, Decimal("-4925.20"))
        self.assertEqual(result.net_amount, Decimal("5672.20"))

    def test_year_end_reconciliation_collects_remaining_tax_on_final_december_cutoff(self) -> None:
        result = self.calculate(
            tax_schedule=replace(self.tax_schedule, calculation_basis="SEMI_MONTHLY"),
            prior_ytd_taxable_income=Decimal("100000"),
            prior_ytd_withholding_tax=Decimal("10000"),
            year_end_wtax_reconciliation_enabled=True,
            is_final_december_cutoff=True,
        )

        self.assertEqual(result.status, "READY")
        self.assertEqual(result.withholding_tax, Decimal("74.72"))

    def test_year_end_reconciliation_is_not_applied_before_final_december_cutoff(self) -> None:
        result = self.calculate(
            tax_schedule=replace(self.tax_schedule, calculation_basis="SEMI_MONTHLY"),
            prior_ytd_withholding_tax=Decimal("25000"),
            year_end_wtax_reconciliation_enabled=True,
            is_final_december_cutoff=False,
        )

        self.assertEqual(result.withholding_tax, Decimal("74.70"))

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
        self.assertEqual(result.taxable_income, Decimal("1247.00"))
        self.assertEqual(result.withholding_tax, Decimal("124.70"))
        self.assertEqual(result.benefit_lines[0].amount, Decimal("600.00"))


if __name__ == "__main__":
    unittest.main()
