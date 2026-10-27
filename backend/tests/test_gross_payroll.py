import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.payroll.domain.entities.gross_payroll import (
    PAY_COMPONENT_CODES,
    Compensation,
    CutoffEmployeeTime,
    EarningRule,
    PayrollGroupPolicy,
    calculate_gross_pay,
    compensation_period_basis,
    monthly_compensation_basis,
)


class GrossPayrollTests(unittest.TestCase):
    def setUp(self) -> None:
        self.employee_id = uuid4()
        self.payroll_group_id = uuid4()
        self.compensation = Compensation(
            id=uuid4(),
            employee_id=self.employee_id,
            payroll_group_id=self.payroll_group_id,
            base_rate=Decimal("10.00"),
            currency="PHP",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            is_active=True,
        )
        self.policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="HOURLY",
            pay_frequency="SEMIMONTHLY",
            standard_minutes_per_day=480,
            annual_divisor=None,
        )
        self.time = CutoffEmployeeTime(
            employee_id=self.employee_id,
            cutoff_result_id=uuid4(),
            required_work_minutes=480,
            component_minutes={
                "regular_minutes": 480,
                "ordinary_ot_minutes": 60,
                "night_regular_minutes": 60,
                "night_ot_minutes": 30,
            },
        )
        self.rules = {
            component: EarningRule(component_code=component, multiplier=Decimal("0"))
            for component in PAY_COMPONENT_CODES
        }
        self.rules.update({
            "REGULAR": EarningRule("REGULAR", Decimal("1")),
            "ORDINARY_OT": EarningRule("ORDINARY_OT", Decimal("1.25")),
            "NIGHT_REGULAR": EarningRule("NIGHT_REGULAR", Decimal("0.10")),
            "NIGHT_OT": EarningRule("NIGHT_OT", Decimal("0.10")),
        })

    def calculate(self, **overrides):
        params = {
            "time": self.time,
            "compensation": self.compensation,
            "policy": self.policy,
            "earning_rules": self.rules,
            "cutoff_period_start": date(2026, 1, 1),
            "cutoff_period_end": date(2026, 1, 15),
        }
        params.update(overrides)
        return calculate_gross_pay(**params)

    def test_compensation_bases_use_configured_annual_divisor(self) -> None:
        for rate_type, base_rate, half_basis, month_basis in (
            ("MONTHLY", "40000", "20000.00", "40000.00"),
            ("DAILY", "850", "11085.42", "22170.83"),
            ("HOURLY", "106.25", "11085.42", "22170.83"),
            ("DAILY", "1", "13.04", "26.08"),
            ("DAILY", "1.03", "13.43", "26.87"),
        ):
            with self.subTest(rate_type=rate_type, base_rate=base_rate):
                policy = replace(self.policy, rate_type=rate_type, annual_divisor=Decimal("313"))
                compensation = replace(self.compensation, base_rate=Decimal(base_rate))
                self.assertEqual(
                    compensation_period_basis(policy, compensation, periods_per_year=24),
                    Decimal(half_basis),
                )
                self.assertEqual(monthly_compensation_basis(policy, compensation), Decimal(month_basis))

    def test_calculates_regular_overtime_and_incremental_night_premiums(self) -> None:
        result = self.calculate()

        self.assertEqual(result.status, "READY")
        self.assertEqual(result.gross_amount, Decimal("94.00"))
        self.assertEqual(
            {line.component_code: line.amount for line in result.lines},
            {
                "REGULAR": Decimal("80.00"),
                "ORDINARY_OT": Decimal("12.50"),
                "NIGHT_REGULAR": Decimal("1.00"),
                "NIGHT_OT": Decimal("0.50"),
                **{
                    code: Decimal("0.00")
                    for code in PAY_COMPONENT_CODES
                    if code not in {"REGULAR", "ORDINARY_OT", "NIGHT_REGULAR", "NIGHT_OT"}
                },
            },
        )

    def test_missing_earning_rule_holds_without_guessing_gross(self) -> None:
        result = self.calculate(earning_rules={})

        self.assertEqual(result.status, "HOLD")
        self.assertIsNone(result.gross_amount)
        self.assertIn("Missing earning rules", result.hold_reason or "")

    def test_missing_approved_attendance_time_holds_calculation(self) -> None:
        time = CutoffEmployeeTime(
            employee_id=self.employee_id,
            cutoff_result_id=uuid4(),
            component_minutes={"regular_minutes": 0},
            incomplete_time_source_count=1,
        )
        result = self.calculate(time=time)

        self.assertEqual(result.status, "HOLD")
        self.assertIsNone(result.gross_amount)
        self.assertIn("missing approved worked-time minutes", result.hold_reason or "")

    def test_monthly_rate_requires_positive_annual_divisor(self) -> None:
        monthly_policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="MONTHLY",
            pay_frequency="SEMIMONTHLY",
            standard_minutes_per_day=480,
            annual_divisor=None,
        )
        result = self.calculate(policy=monthly_policy)

        self.assertEqual(result.status, "HOLD")
        self.assertIsNone(result.gross_amount)
        self.assertIn("annual divisor", result.hold_reason or "")

    def test_monthly_rate_uses_configured_annual_divisor(self) -> None:
        monthly_policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="MONTHLY",
            pay_frequency="SEMIMONTHLY",
            standard_minutes_per_day=480,
            annual_divisor=Decimal("260"),
        )
        monthly_compensation = Compensation(
            id=self.compensation.id,
            employee_id=self.employee_id,
            payroll_group_id=self.payroll_group_id,
            base_rate=Decimal("31200.00"),
            currency="PHP",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            is_active=True,
        )
        time = CutoffEmployeeTime(
            employee_id=self.employee_id,
            cutoff_result_id=uuid4(),
            component_minutes={"regular_minutes": 480},
        )
        result = self.calculate(
            time=time,
            compensation=monthly_compensation,
            policy=monthly_policy,
        )

        self.assertEqual(result.status, "READY")
        self.assertEqual(result.gross_amount, Decimal("15600.00"))
        self.assertEqual(result.lines[0].component_code, "MONTHLY_BASE")
        self.assertEqual(result.lines[0].amount, Decimal("15600.00"))

    def test_monthly_semimonthly_salary_deducts_unpaid_scheduled_minutes(self) -> None:
        monthly_policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="MONTHLY",
            pay_frequency="SEMIMONTHLY",
            standard_minutes_per_day=480,
            annual_divisor=Decimal("313"),
        )
        monthly_compensation = replace(
            self.compensation,
            base_rate=Decimal("20000.00"),
        )
        time = replace(
            self.time,
            required_work_minutes=480,
            component_minutes={
                "regular_minutes": 420,
                "late_minutes": 30,
                "undertime_minutes": 30,
            },
        )

        result = self.calculate(
            time=time,
            compensation=monthly_compensation,
            policy=monthly_policy,
        )

        self.assertEqual(result.gross_amount, Decimal("9904.15"))
        unpaid_line = next(
            line for line in result.lines if line.component_code == "UNPAID_TIME_DEDUCTION"
        )
        self.assertEqual(unpaid_line.minutes, 60)
        self.assertEqual(unpaid_line.amount, Decimal("-95.85"))

    def test_rest_day_work_does_not_cover_required_scheduled_minutes(self) -> None:
        monthly_policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="MONTHLY",
            pay_frequency="SEMIMONTHLY",
            standard_minutes_per_day=480,
            annual_divisor=Decimal("313"),
        )
        time = replace(
            self.time,
            required_work_minutes=480,
            component_minutes={
                "regular_minutes": 420,
                "rest_day_minutes": 480,
            },
        )

        result = self.calculate(
            time=time,
            compensation=replace(self.compensation, base_rate=Decimal("20000.00")),
            policy=monthly_policy,
        )

        unpaid_line = next(
            line for line in result.lines if line.component_code == "UNPAID_TIME_DEDUCTION"
        )
        rest_day_line = next(line for line in result.lines if line.component_code == "REST_DAY")
        self.assertEqual(unpaid_line.minutes, 60)
        self.assertEqual(rest_day_line.minutes, 480)

    def test_monthly_pay_frequency_sets_salary_period_amount(self) -> None:
        monthly_policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="MONTHLY",
            pay_frequency="MONTHLY",
            standard_minutes_per_day=480,
            annual_divisor=Decimal("313"),
        )
        result = self.calculate(
            policy=monthly_policy,
            compensation=replace(self.compensation, base_rate=Decimal("20000")),
            time=replace(self.time, component_minutes={"regular_minutes": 480}),
        )

        self.assertEqual(result.gross_amount, Decimal("20000.00"))

    def test_monthly_salary_is_paid_for_cutoff_without_scheduled_days(self) -> None:
        monthly_policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="MONTHLY",
            pay_frequency="SEMIMONTHLY",
            standard_minutes_per_day=480,
            annual_divisor=Decimal("313"),
        )
        result = self.calculate(
            policy=monthly_policy,
            compensation=replace(self.compensation, base_rate=Decimal("20000")),
            time=replace(
                self.time,
                required_work_minutes=0,
                component_minutes={"regular_minutes": 0},
            ),
        )

        self.assertEqual(result.gross_amount, Decimal("10000.00"))

    def test_monthly_contribution_basis_uses_configured_annual_divisor(self) -> None:
        daily_policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="DAILY",
            pay_frequency="SEMIMONTHLY",
            standard_minutes_per_day=480,
            annual_divisor=Decimal("260"),
        )
        basis = monthly_compensation_basis(daily_policy, replace(self.compensation, base_rate=Decimal("100")))
        self.assertEqual(basis, Decimal("2166.67"))
        self.assertIsNone(
            monthly_compensation_basis(
                replace(daily_policy, annual_divisor=None),
                self.compensation,
            )
        )

    def test_result_is_ready_without_employee_or_supervisor_acknowledgment(self) -> None:
        time = CutoffEmployeeTime(
            employee_id=self.employee_id,
            cutoff_result_id=uuid4(),
            component_minutes={"regular_minutes": 480},
        )
        result = self.calculate(time=time)

        self.assertEqual(result.status, "READY")
        self.assertIsNone(result.hold_reason)
        self.assertEqual(result.gross_amount, Decimal("80.00"))

if __name__ == "__main__":
    unittest.main()
