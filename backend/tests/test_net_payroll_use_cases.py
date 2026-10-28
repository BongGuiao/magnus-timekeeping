import unittest
from dataclasses import replace
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
from app.payroll.domain.entities.statutory_schedules import (
    ContributionBracket,
    WithholdingTaxBracket,
    WithholdingTaxSchedule,
)


class FakePayrollRepository:
    def __init__(self) -> None:
        self.employee_id = uuid4()
        self.cutoff_id = uuid4()
        self.payroll_group_id = uuid4()
        self.policy = PayrollGroupPolicy(
            payroll_group_id=self.payroll_group_id,
            rate_type="HOURLY",
            pay_frequency="SEMIMONTHLY",
            standard_minutes_per_day=480,
            annual_divisor=Decimal("260"),
        )
        self.cutoff = CutoffPayrollData(
            cutoff_id=self.cutoff_id,
            cutoff_code="2026-01-A",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 15),
            is_locked=False,
            is_attendance_finalized=True,
            payroll_group=self.policy,
            employees=(
                CutoffEmployeeTime(
                    employee_id=self.employee_id,
                    cutoff_result_id=uuid4(),
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
        self.loader_calls: list[tuple[str, tuple]] = []

    async def load_cutoff_payroll_data(self, cutoff_id):
        return self.cutoff

    async def list_earning_rules(self, payroll_group_id):
        return self.rules

    async def load_covering_compensations(self, employee_ids, *args):
        self.loader_calls.append(("compensations", tuple(employee_ids)))
        return {employee_id: self.compensation for employee_id in employee_ids}

    async def load_net_payroll_inputs(self, cutoff_id, employee_ids):
        self.loader_calls.append(("net_inputs", tuple(employee_ids)))
        return {employee_id: self.net_inputs for employee_id in employee_ids}

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
    async def test_half_month_bracket_and_monthly_reconciliation_for_monthly_and_daily_groups(self) -> None:
        for rate_type, base_rate in (("MONTHLY", "40000"), ("DAILY", "850")):
            with self.subTest(rate_type=rate_type):
                repository = FakePayrollRepository()
                repository.policy = replace(
                    repository.policy,
                    rate_type=rate_type,
                    annual_divisor=Decimal("313"),
                )
                repository.compensation = replace(
                    repository.compensation, base_rate=Decimal(base_rate)
                )
                repository.cutoff = replace(
                    repository.cutoff,
                    payroll_group=repository.policy,
                    cutoff_half="FIRST_HALF",
                    employees=(replace(
                        repository.cutoff.employees[0],
                        required_work_minutes=4800,
                        component_minutes={"regular_minutes": 4800},
                    ),),
                )
                brackets = {}
                for program in ("SSS", "PHILHEALTH", "PAGIBIG"):
                    lower = ContributionBracket(
                        id=uuid4(), schedule_id=uuid4(), bracket_number=1,
                        compensation_min=Decimal(0), compensation_max=Decimal("20000"),
                        contribution_base=Decimal("11000"),
                        employee_rate=Decimal("0.05"), employer_rate=Decimal("0.10"),
                        employee_fixed_amount=Decimal("10"), employer_fixed_amount=Decimal("20"),
                        employer_additional_fixed_amount=Decimal("30"),
                        employee_contribution_cap=Decimal("10000") if program == "PAGIBIG" else None,
                        employer_contribution_cap=Decimal("10000") if program == "PAGIBIG" else None,
                    )
                    brackets[program] = (lower, replace(
                        lower, id=uuid4(), bracket_number=2,
                        compensation_min=Decimal("20000.01"), compensation_max=None,
                        contribution_base=Decimal("22000"),
                    ))
                now = datetime.now(timezone.utc)
                tax_schedule = WithholdingTaxSchedule(
                    id=uuid4(), schedule_name="Test", effective_from=date(2026, 1, 1),
                    effective_to=None, tax_exempt_benefit_limit=Decimal(0),
                    source_reference="Test", status="ACTIVE", created_at=now,
                    created_by=None, updated_at=now, updated_by=None, row_version=1,
                )
                repository.net_inputs = replace(
                    repository.net_inputs,
                    cutoff_half="FIRST_HALF",
                    contribution_brackets=brackets,
                    tax_schedule=tax_schedule,
                    tax_brackets=(WithholdingTaxBracket(
                        id=uuid4(), schedule_id=tax_schedule.id, bracket_number=1,
                        annual_income_min=Decimal(0), annual_income_max=None,
                        base_tax=Decimal(0), marginal_rate=Decimal(0), excess_over=Decimal(0),
                    ),),
                )
                use_cases = PayrollUseCases(repository)
                first = (await use_cases.calculate_payroll(repository.cutoff_id, uuid4())).results[0]
                self.assertEqual(first.status, "READY")
                self.assertEqual(first.contribution_lines[0].employee_amount, Decimal("560.00"))
                self.assertEqual(first.contribution_lines[0].employer_amount, Decimal("1150.00"))
                repository.cutoff = replace(repository.cutoff, cutoff_half="SECOND_HALF")
                repository.net_inputs = replace(
                    repository.net_inputs,
                    cutoff_half="SECOND_HALF",
                    prior_month_employee_contributions={
                        line.program_code: line.employee_amount for line in first.contribution_lines
                    },
                    prior_month_employer_contributions={
                        line.program_code: line.employer_amount for line in first.contribution_lines
                    },
                )
                second = (await use_cases.calculate_payroll(repository.cutoff_id, uuid4())).results[0]
                self.assertEqual(second.status, "READY")
                self.assertEqual(second.contribution_lines[0].employee_amount, Decimal("550.00"))
                self.assertEqual(second.contribution_lines[0].employer_amount, Decimal("1100.00"))
                repository.net_inputs = replace(
                    repository.net_inputs, statutory_contribution_timing="FINAL_CUTOFF"
                )
                final = (await use_cases.calculate_payroll(repository.cutoff_id, uuid4())).results[0]
                self.assertEqual(final.status, "READY")
                for first_line, second_line, final_line in zip(
                    first.contribution_lines, second.contribution_lines, final.contribution_lines
                ):
                    self.assertEqual(
                        first_line.employee_amount + second_line.employee_amount,
                        final_line.employee_amount,
                    )
                    self.assertEqual(
                        first_line.employer_amount + second_line.employer_amount,
                        final_line.employer_amount,
                    )
                repository.cutoff = replace(repository.cutoff, cutoff_half="FIRST_HALF")
                repository.net_inputs = replace(repository.net_inputs, cutoff_half="FIRST_HALF")
                deferred = (await use_cases.calculate_payroll(repository.cutoff_id, uuid4())).results[0]
                self.assertEqual(deferred.status, "READY")
                self.assertEqual(deferred.employee_contributions, Decimal("0.00"))
                self.assertEqual(deferred.employer_contributions, Decimal("0.00"))

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

    async def test_payroll_calculation_requires_finalized_attendance(self) -> None:
        repository = FakePayrollRepository()
        repository.cutoff = replace(repository.cutoff, is_attendance_finalized=False)

        with self.assertRaisesRegex(ValueError, "Finalize attendance"):
            await PayrollUseCases(repository).calculate_payroll(
                repository.cutoff_id,
                uuid4(),
            )

        self.assertEqual(repository.loader_calls, [])

    async def test_payroll_inputs_are_loaded_once_for_all_employees(self) -> None:
        repository = FakePayrollRepository()
        template = repository.cutoff.employees[0]
        employees = (template,) + tuple(
            CutoffEmployeeTime(
                employee_id=uuid4(),
                cutoff_result_id=uuid4(),
                component_minutes={"regular_minutes": 480},
            )
            for _ in range(49)
        )
        repository.cutoff = replace(repository.cutoff, employees=employees)

        result = await PayrollUseCases(repository).calculate_payroll(
            repository.cutoff_id,
            uuid4(),
        )

        employee_ids = tuple(employee.employee_id for employee in employees)
        self.assertEqual(
            repository.loader_calls,
            [("compensations", employee_ids), ("net_inputs", employee_ids)],
        )
        self.assertEqual(len(result.results), 50)


if __name__ == "__main__":
    unittest.main()
