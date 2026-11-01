import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.filemaintenance.payroll_cutoffs.domain.entities.employee_cutoff_result import (
    UnworkedHolidayFact,
    calculate_employee_cutoff_totals,
)
from app.filemaintenance.payroll_cutoffs.domain.holiday_pay_eligibility import (
    DayAttendanceFacts,
    classify_day,
    holiday_pay_qualifies,
)
from app.payroll.domain.entities.gross_payroll import (
    PAY_COMPONENT_CODES,
    Compensation,
    CutoffEmployeeTime,
    EarningRule,
    PayrollGroupPolicy,
    calculate_gross_pay,
)


class ClassifyDayTests(unittest.TestCase):
    def test_worked_day_is_present_even_on_rest_day_or_holiday(self) -> None:
        self.assertEqual(classify_day(DayAttendanceFacts(worked=True, is_workday=False)), "PRESENT")

    def test_non_working_day_is_skipped(self) -> None:
        self.assertEqual(classify_day(DayAttendanceFacts(worked=False, is_workday=False)), "SKIP")

    def test_paid_leave_and_official_business_count_as_present(self) -> None:
        for facts in (
            DayAttendanceFacts(worked=False, is_workday=True, paid_leave=True),
            DayAttendanceFacts(worked=False, is_workday=True, official_business=True),
            DayAttendanceFacts(worked=False, is_workday=True, schedule_credited=True),
        ):
            with self.subTest(facts=facts):
                self.assertEqual(classify_day(facts), "PRESENT")

    def test_unexcused_or_unpaid_leave_workday_is_absent(self) -> None:
        self.assertEqual(classify_day(DayAttendanceFacts(worked=False, is_workday=True)), "ABSENT")
        self.assertEqual(
            classify_day(
                DayAttendanceFacts(
                    worked=False, is_workday=True, unpaid_leave=True, schedule_credited=True
                )
            ),
            "ABSENT",
        )

    def test_future_or_pre_employment_day_is_unknown(self) -> None:
        self.assertEqual(
            classify_day(DayAttendanceFacts(worked=False, is_workday=True, is_future=True)),
            "UNKNOWN",
        )
        self.assertEqual(
            classify_day(DayAttendanceFacts(worked=False, is_workday=True, employed=False)),
            "UNKNOWN",
        )


class HolidayPayQualifiesTests(unittest.TestCase):
    def test_before_only_ignores_absence_after_holiday(self) -> None:
        self.assertTrue(holiday_pay_qualifies("BEFORE_ONLY", "PRESENT", "ABSENT"))
        self.assertFalse(holiday_pay_qualifies("BEFORE_ONLY", "ABSENT", "PRESENT"))

    def test_before_and_after_requires_both_workdays(self) -> None:
        self.assertTrue(holiday_pay_qualifies("BEFORE_AND_AFTER", "PRESENT", "PRESENT"))
        self.assertFalse(holiday_pay_qualifies("BEFORE_AND_AFTER", "PRESENT", "ABSENT"))
        self.assertFalse(holiday_pay_qualifies("BEFORE_AND_AFTER", "ABSENT", "PRESENT"))

    def test_unknown_never_disqualifies(self) -> None:
        self.assertTrue(holiday_pay_qualifies("BEFORE_AND_AFTER", "UNKNOWN", "UNKNOWN"))


class UnworkedHolidayTotalsTests(unittest.TestCase):
    def test_splits_qualified_regular_double_and_disqualified_minutes(self) -> None:
        employee_id = uuid4()
        totals = calculate_employee_cutoff_totals(
            employee_ids=[employee_id],
            attendance=[],
            leaves=[],
            overtime=[],
            official_business=[],
            exceptions=[],
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 15),
            unworked_holidays=[
                UnworkedHolidayFact(employee_id, date(2026, 4, 2), "RH", 480, True),
                UnworkedHolidayFact(employee_id, date(2026, 4, 3), "DBL", 480, True),
                UnworkedHolidayFact(employee_id, date(2026, 4, 9), "RH", 480, False),
                UnworkedHolidayFact(employee_id, date(2026, 4, 10), "DBL", 480, False),
                UnworkedHolidayFact(employee_id, date(2026, 4, 30), "RH", 480, True),
                UnworkedHolidayFact(employee_id, date(2026, 4, 11), "SNW", 480, True),
            ],
        )

        self.assertEqual(totals[0].unworked_holiday_minutes, 480)
        self.assertEqual(totals[0].unworked_double_holiday_minutes, 480)
        self.assertEqual(totals[0].disqualified_holiday_minutes, 480 + 960)
        self.assertEqual(totals[0].required_work_minutes, 0)


class UnworkedHolidayGrossPayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.employee_id = uuid4()
        self.payroll_group_id = uuid4()
        self.compensation = Compensation(
            id=uuid4(),
            employee_id=self.employee_id,
            payroll_group_id=self.payroll_group_id,
            base_rate=Decimal("800.00"),
            currency="PHP",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            is_active=True,
        )
        self.policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="DAILY",
            pay_frequency="SEMIMONTHLY",
            standard_minutes_per_day=480,
            annual_divisor=Decimal("313"),
        )
        self.rules = {
            code: EarningRule(code, Decimal("1")) for code in PAY_COMPONENT_CODES
        }
        self.rules["UNWORKED_DOUBLE_HOLIDAY"] = EarningRule("UNWORKED_DOUBLE_HOLIDAY", Decimal("2"))

    def calculate(self, time: CutoffEmployeeTime, **overrides):
        params = {
            "time": time,
            "compensation": self.compensation,
            "policy": self.policy,
            "earning_rules": self.rules,
            "cutoff_period_start": date(2026, 4, 1),
            "cutoff_period_end": date(2026, 4, 15),
        }
        params.update(overrides)
        return calculate_gross_pay(**params)

    def time(self, **minutes) -> CutoffEmployeeTime:
        return CutoffEmployeeTime(
            employee_id=self.employee_id,
            cutoff_result_id=uuid4(),
            component_minutes=minutes,
        )

    def test_daily_rate_pays_unworked_regular_and_double_holidays(self) -> None:
        result = self.calculate(
            self.time(unworked_holiday_minutes=480, unworked_double_holiday_minutes=480)
        )

        amounts = {line.component_code: line.amount for line in result.lines}
        self.assertEqual(result.status, "READY")
        self.assertEqual(amounts["UNWORKED_HOLIDAY"], Decimal("800.00"))
        self.assertEqual(amounts["UNWORKED_DOUBLE_HOLIDAY"], Decimal("1600.00"))
        self.assertEqual(result.gross_amount, Decimal("2400.00"))

    def test_daily_rate_holds_only_when_needed_unworked_rule_is_missing(self) -> None:
        rules = {
            code: rule
            for code, rule in self.rules.items()
            if code not in {"UNWORKED_HOLIDAY", "UNWORKED_DOUBLE_HOLIDAY"}
        }

        no_holiday = self.calculate(self.time(regular_minutes=480), earning_rules=rules)
        with_holiday = self.calculate(self.time(unworked_holiday_minutes=480), earning_rules=rules)

        self.assertEqual(no_holiday.status, "READY")
        self.assertEqual(no_holiday.gross_amount, Decimal("800.00"))
        self.assertEqual(with_holiday.status, "HOLD")
        self.assertIn("UNWORKED_HOLIDAY", with_holiday.hold_reason or "")

    def test_monthly_rate_ignores_unworked_credit_and_deducts_disqualified_holiday(self) -> None:
        policy = replace(self.policy, rate_type="MONTHLY", annual_divisor=Decimal("365"))
        compensation = replace(self.compensation, base_rate=Decimal("36500.00"))
        qualified = self.calculate(
            self.time(unworked_holiday_minutes=480),
            policy=policy,
            compensation=compensation,
        )
        disqualified = self.calculate(
            replace(
                self.time(),
                disqualified_holiday_minutes=480,
            ),
            policy=policy,
            compensation=compensation,
        )

        self.assertEqual(qualified.gross_amount, Decimal("18250.00"))
        self.assertNotIn("UNWORKED_HOLIDAY", {line.component_code for line in qualified.lines})
        deduction = next(
            line for line in disqualified.lines if line.component_code == "UNPAID_TIME_DEDUCTION"
        )
        self.assertEqual(deduction.minutes, 480)
        self.assertEqual(deduction.amount, Decimal("-1200.00"))
        self.assertEqual(disqualified.gross_amount, Decimal("17050.00"))


if __name__ == "__main__":
    unittest.main()
