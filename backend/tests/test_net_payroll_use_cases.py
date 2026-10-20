import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.payroll.application.use_cases import PayrollUseCases
from app.payroll.domain.entities.gross_payroll import (
    PAY_COMPONENT_CODES,
    Compensation,
    CutoffEmployeeTime,
    CutoffPayrollData,
    EarningRule,
    GrossPayRun,
    PayrollGroupPolicy,
)
from app.payroll.domain.entities.net_payroll import NetPayrollInputs


class FakePayrollRepository:
    def __init__(self) -> None:
        self.employee_id = uuid4()
        self.cutoff_id = uuid4()
        self.payroll_group_id = uuid4()
        self.policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="HOURLY",
            standard_minutes_per_day=480,
            annual_divisor=Decimal("260"),
        )
        self.cutoff = CutoffPayrollData(
            cutoff_id=self.cutoff_id,
            cutoff_code="2026-01-A",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 15),
            is_locked=False,
            payroll_group=self.policy,
            employees=(
                CutoffEmployeeTime(
                    employee_id=self.employee_id,
                    cutoff_result_id=uuid4(),
                    employee_confirmation_status="ACKNOWLEDGED",
                    supervisor_status="ACKNOWLEDGED",
                    hr_status="ACKNOWLEDGED",
                    component_minutes={"regular_minutes": 480},
                ),
            ),
        )
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
        self.rules = [
            EarningRule(component_code=code, multiplier=Decimal("1") if code == "REGULAR" else Decimal("0"))
            for code in PAY_COMPONENT_CODES
        ]
        self.net_inputs = NetPayrollInputs(
            benefits=(),
            contribution_brackets={},
            tax_schedule=None,
            tax_brackets=(),
            monthly_cutoff_count=2,
            cutoff_number_in_month=1,
            prior_month_employee_contributions={},
            prior_month_employer_contributions={},
            prior_ytd_taxable_income=Decimal(0),
            prior_ytd_withholding_tax=Decimal(0),
            prior_ytd_limited_exempt_benefits=Decimal(0),
        )
        self.saved_results = []

    async def load_cutoff_payroll_data(self, cutoff_id):
        return self.cutoff

    async def list_earning_rules(self, payroll_group_id):
        return self.rules

    async def load_covering_compensation(self, *args):
        return self.compensation

    async def load_net_payroll_inputs(self, cutoff_id, employee_id):
        return self.net_inputs

    async def save_gross_pay_run(self, **kwargs):
        self.saved_results = kwargs["results"]
        return GrossPayRun(
            id=uuid4(),
            cutoff_id=kwargs["cutoff_id"],
            calculation_version="GROSS_PAY_V1",
            calculated_at=datetime.now(timezone.utc),
            calculated_by=kwargs["actor_id"],
            results=tuple(self.saved_results),
        )


class NetPayrollUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_schedules_hold_full_payroll_but_preserve_gross(self) -> None:
        repository = FakePayrollRepository()
        result = await PayrollUseCases(repository).calculate_payroll(
            repository.cutoff_id,
            uuid4(),
        )

        employee_result = result.results[0]
        self.assertEqual(employee_result.gross_status, "READY")
        self.assertEqual(employee_result.gross_amount, Decimal("80.00"))
        self.assertEqual(employee_result.status, "HOLD")
        self.assertIsNone(employee_result.net_amount)
        self.assertIn("Missing active statutory schedules", employee_result.hold_reason or "")


if __name__ == "__main__":
    unittest.main()
