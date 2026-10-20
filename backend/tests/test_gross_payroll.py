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
            standard_minutes_per_day=480,
            annual_divisor=None,
        )
        self.time = CutoffEmployeeTime(
            employee_id=self.employee_id,
            cutoff_result_id=uuid4(),
            employee_confirmation_status="ACKNOWLEDGED",
            supervisor_status="ACKNOWLEDGED",
            hr_status="ACKNOWLEDGED",
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
            employee_confirmation_status="ACKNOWLEDGED",
            supervisor_status="ACKNOWLEDGED",
            hr_status="ACKNOWLEDGED",
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
            employee_confirmation_status="ACKNOWLEDGED",
            supervisor_status="ACKNOWLEDGED",
            hr_status="ACKNOWLEDGED",
            component_minutes={"regular_minutes": 480},
        )
        result = self.calculate(
            time=time,
            compensation=monthly_compensation,
            policy=monthly_policy,
        )

        self.assertEqual(result.status, "READY")
        self.assertEqual(result.gross_amount, Decimal("1440.00"))

    def test_monthly_contribution_basis_uses_configured_annual_divisor(self) -> None:
        daily_policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="DAILY",
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

    def test_unacknowledged_result_is_held_even_when_amount_is_calculated(self) -> None:
        unacknowledged_time = CutoffEmployeeTime(
            employee_id=self.employee_id,
            cutoff_result_id=uuid4(),
            employee_confirmation_status="PENDING",
            supervisor_status="ACKNOWLEDGED",
            hr_status="ACKNOWLEDGED",
            component_minutes={"regular_minutes": 480},
        )
        result = self.calculate(time=unacknowledged_time)

        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.gross_amount, Decimal("80.00"))
        self.assertIn("acknowledgments are required", result.hold_reason or "")


if __name__ == "__main__":
    unittest.main()
