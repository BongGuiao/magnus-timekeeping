import asyncio
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.payroll.application.off_cycle_inputs import (
    CreateOffCycleBenefitRunInput,
    CreateThirteenthMonthOffCycleRunInput,
    OffCycleEmployee,
    OffCycleUploadRow,
    ThirteenthMonthPayable,
)
from app.payroll.application.off_cycle_use_cases import OffCyclePayrollUseCases
from app.payroll.domain.entities.benefits import BenefitType
from app.payroll.domain.entities.off_cycle import (
    OffCyclePayrollLine,
    OffCyclePayrollRun,
    ensure_off_cycle_action_allowed,
    validate_off_cycle_payment_dates,
)
from app.payroll.domain.entities.statutory_schedules import WithholdingTaxBracket
from app.payroll.domain.services.off_cycle_tax import (
    OffCycleTaxContext,
    OffCycleYtd,
    calculate_off_cycle_line,
)


NOW = datetime(2026, 12, 1, tzinfo=timezone.utc)


def _brackets() -> tuple[WithholdingTaxBracket, ...]:
    schedule_id = uuid4()
    return (
        WithholdingTaxBracket(
            id=uuid4(),
            schedule_id=schedule_id,
            bracket_number=1,
            annual_income_min=Decimal("0"),
            annual_income_max=Decimal("250000"),
            base_tax=Decimal("0"),
            marginal_rate=Decimal("0"),
            excess_over=Decimal("0"),
        ),
        WithholdingTaxBracket(
            id=uuid4(),
            schedule_id=schedule_id,
            bracket_number=2,
            annual_income_min=Decimal("250000.01"),
            annual_income_max=None,
            base_tax=Decimal("0"),
            marginal_rate=Decimal("0.15"),
            excess_over=Decimal("250000"),
        ),
    )


TAX = OffCycleTaxContext(
    calculation_basis="ANNUAL_YTD",
    brackets=_brackets(),
    tax_exempt_benefit_limit=Decimal("90000"),
)


def _ytd(taxable: str = "0", withheld: str = "0", exempt: str = "0") -> OffCycleYtd:
    return OffCycleYtd(
        taxable_income=Decimal(taxable),
        withholding_tax=Decimal(withheld),
        exempt_limited_benefits=Decimal(exempt),
    )


class OffCycleTaxTests(unittest.TestCase):
    def test_taxable_incentive_withholds_incremental_annual_tax(self) -> None:
        result = calculate_off_cycle_line(
            amount=Decimal("20000"),
            tax_treatment="TAXABLE",
            withholding_timing="PAY_PERIOD",
            ytd=_ytd(taxable="240000"),
            tax=TAX,
        )
        self.assertEqual(result.taxable_amount, Decimal("20000.00"))
        self.assertEqual(result.withholding_tax, Decimal("1500.00"))
        self.assertEqual(result.net_amount, Decimal("18500.00"))

    def test_year_end_timing_defers_withholding(self) -> None:
        result = calculate_off_cycle_line(
            amount=Decimal("20000"),
            tax_treatment="TAXABLE",
            withholding_timing="YEAR_END",
            ytd=_ytd(taxable="400000"),
            tax=TAX,
        )
        self.assertEqual(result.taxable_amount, Decimal("20000.00"))
        self.assertEqual(result.withholding_tax, Decimal("0.00"))
        self.assertEqual(result.net_amount, Decimal("20000.00"))

    def test_exempt_limited_uses_remaining_shared_exemption(self) -> None:
        result = calculate_off_cycle_line(
            amount=Decimal("30000"),
            tax_treatment="EXEMPT_LIMITED",
            withholding_timing="PAY_PERIOD",
            ytd=_ytd(taxable="300000", exempt="80000"),
            tax=TAX,
        )
        self.assertEqual(result.exempt_limited_amount, Decimal("10000.00"))
        self.assertEqual(result.taxable_amount, Decimal("20000.00"))
        self.assertEqual(result.withholding_tax, Decimal("3000.00"))

    def test_exempt_benefit_is_never_taxed(self) -> None:
        result = calculate_off_cycle_line(
            amount=Decimal("5000"),
            tax_treatment="EXEMPT",
            withholding_timing="PAY_PERIOD",
            ytd=_ytd(taxable="500000"),
            tax=TAX,
        )
        self.assertEqual(result.taxable_amount, Decimal("0.00"))
        self.assertEqual(result.withholding_tax, Decimal("0.00"))

    def test_cumulative_method_collects_tax_on_earlier_deferred_incentives(self) -> None:
        # 300,000 YTD taxable includes a 50,000 incentive paid without withholding.
        # Tax already withheld (0) only covers the first 250,000.
        result = calculate_off_cycle_line(
            amount=Decimal("20000"),
            tax_treatment="EXEMPT_LIMITED",
            withholding_timing="PAY_PERIOD",
            ytd=_ytd(taxable="300000", withheld="0", exempt="0"),
            tax=TAX,
            method="CUMULATIVE",
        )
        self.assertEqual(result.taxable_amount, Decimal("0.00"))
        self.assertEqual(result.withholding_tax, Decimal("7500.00"))
        self.assertEqual(result.net_amount, Decimal("12500.00"))

    def test_withholding_never_exceeds_payment(self) -> None:
        result = calculate_off_cycle_line(
            amount=Decimal("1000"),
            tax_treatment="EXEMPT_LIMITED",
            withholding_timing="PAY_PERIOD",
            ytd=_ytd(taxable="400000"),
            tax=TAX,
            method="CUMULATIVE",
        )
        self.assertEqual(result.withholding_tax, Decimal("1000.00"))
        self.assertEqual(result.net_amount, Decimal("0.00"))

    def test_semi_monthly_basis_annualizes_per_period_brackets(self) -> None:
        schedule_id = uuid4()
        per_period = (
            WithholdingTaxBracket(
                id=uuid4(),
                schedule_id=schedule_id,
                bracket_number=1,
                annual_income_min=Decimal("0"),
                annual_income_max=None,
                base_tax=Decimal("0"),
                marginal_rate=Decimal("0.10"),
                excess_over=Decimal("0"),
            ),
        )
        result = calculate_off_cycle_line(
            amount=Decimal("2400"),
            tax_treatment="TAXABLE",
            withholding_timing="PAY_PERIOD",
            ytd=_ytd(taxable="24000"),
            tax=OffCycleTaxContext(
                calculation_basis="SEMI_MONTHLY",
                brackets=per_period,
                tax_exempt_benefit_limit=Decimal("90000"),
            ),
        )
        self.assertEqual(result.withholding_tax, Decimal("240.00"))


class OffCycleDomainRuleTests(unittest.TestCase):
    def test_status_transitions(self) -> None:
        ensure_off_cycle_action_allowed("DRAFT", "SUBMIT")
        ensure_off_cycle_action_allowed("PENDING", "APPROVE")
        ensure_off_cycle_action_allowed("APPROVED", "MARK_PAID")
        with self.assertRaises(ValueError):
            ensure_off_cycle_action_allowed("DRAFT", "APPROVE")
        with self.assertRaises(ValueError):
            ensure_off_cycle_action_allowed("PAID", "REJECT")
        with self.assertRaises(ValueError):
            ensure_off_cycle_action_allowed("PAID", "DELETE")

    def test_actual_payment_must_stay_in_tax_year(self) -> None:
        validate_off_cycle_payment_dates(date(2026, 12, 15), date(2026, 12, 20))
        with self.assertRaisesRegex(ValueError, "same tax year"):
            validate_off_cycle_payment_dates(date(2026, 12, 15), date(2027, 1, 5))


class _FakeRepository:
    def __init__(self, benefit_type: BenefitType, company_id: UUID):
        self.benefit_type = benefit_type
        self.company_id = company_id
        self.employees: dict[str, OffCycleEmployee] = {}
        self.payables: list[ThirteenthMonthPayable] = []
        self.ytd: dict[UUID, OffCycleYtd] = {}
        self.runs: dict[UUID, OffCyclePayrollRun] = {}
        self.ytd_calls: list[dict] = []

    async def get_payroll_group_company_id(self, payroll_group_id):
        return self.company_id

    async def get_benefit_type(self, benefit_type_id):
        return self.benefit_type

    async def find_group_employees(self, payroll_group_id, employee_nos):
        return {no: self.employees[no] for no in employee_nos if no in self.employees}

    async def list_thirteenth_month_payables(self, thirteenth_month_run_id, payroll_group_id):
        return self.payables

    async def load_tax_context(self, as_of):
        return TAX

    async def load_ytd(self, **kwargs):
        self.ytd_calls.append(kwargs)
        return {
            employee_id: self.ytd.get(employee_id, _ytd())
            for employee_id in kwargs["employee_ids"]
        }

    async def create_run(self, data):
        run_id = uuid4()
        run = OffCyclePayrollRun(
            id=run_id,
            company_id=data.company_id,
            payroll_group_id=data.payroll_group_id,
            benefit_type_id=data.benefit_type_id,
            benefit_code=self.benefit_type.code,
            benefit_name=self.benefit_type.name,
            run_type=data.run_type,
            status="DRAFT",
            proposed_payment_date=data.proposed_payment_date,
            actual_payment_date=None,
            notes=data.notes,
            rejection_reason=None,
            created_by=data.created_by,
            created_at=NOW,
            submitted_at=None,
            approved_by=None,
            approved_at=None,
            paid_by=None,
            paid_at=None,
            thirteenth_month_run_id=data.thirteenth_month_run_id,
            lines=tuple(self._line(run_id, line) for line in data.lines),
        )
        self.runs[run_id] = run
        return run

    def _line(self, run_id, line):
        return OffCyclePayrollLine(
            id=uuid4(),
            run_id=run_id,
            employee_id=line.employee_id,
            employee_no=line.employee_no,
            employee_name=line.employee_no,
            benefit_code=self.benefit_type.code,
            benefit_name=self.benefit_type.name,
            category=self.benefit_type.category,
            tax_treatment=self.benefit_type.tax_treatment,
            withholding_timing=self.benefit_type.withholding_timing,
            amount=line.amount,
            taxable_amount=line.taxable_amount,
            exempt_limited_amount=line.exempt_limited_amount,
            withholding_tax=line.withholding_tax,
            net_amount=line.net_amount,
            notes=line.notes,
            thirteenth_month_result_id=line.thirteenth_month_result_id,
        )

    async def get_run(self, run_id):
        if run_id not in self.runs:
            raise LookupError("Off-cycle payroll run not found.")
        return self.runs[run_id]

    async def replace_lines(self, run_id, expected_status, lines):
        run = self.runs[run_id]
        assert run.status == expected_status
        self.runs[run_id] = replace(
            run, lines=tuple(self._line(run_id, line) for line in lines)
        )
        return self.runs[run_id]

    async def transition_run(self, run_id, transition):
        run = self.runs[run_id]
        assert run.status == transition.expected_status
        changes: dict = {"status": transition.new_status}
        if transition.new_status == "APPROVED":
            changes.update(approved_by=transition.actor_id, approved_at=transition.occurred_at)
        if transition.new_status == "PAID":
            changes.update(
                paid_by=transition.actor_id,
                paid_at=transition.occurred_at,
                actual_payment_date=transition.actual_payment_date,
            )
        if transition.new_status == "REJECTED":
            changes.update(rejection_reason=transition.rejection_reason)
        self.runs[run_id] = replace(run, **changes)
        return self.runs[run_id]

    async def delete_run(self, run_id, allowed_statuses):
        del self.runs[run_id]


def _benefit_type(**overrides) -> BenefitType:
    values = dict(
        id=uuid4(),
        payroll_group_id=uuid4(),
        code="PERF",
        name="Performance incentive",
        category="ONE_TIME_BONUS",
        tax_treatment="TAXABLE",
        is_active=True,
        created_at=NOW,
        created_by=uuid4(),
        updated_at=NOW,
        updated_by=uuid4(),
        row_version=1,
    )
    values.update(overrides)
    return BenefitType(**values)


class OffCycleUseCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.benefit_type = _benefit_type()
        self.group_id = self.benefit_type.payroll_group_id
        self.repository = _FakeRepository(self.benefit_type, uuid4())
        self.employee = OffCycleEmployee(uuid4(), "EMP-0001", "Juan Dela Cruz")
        self.repository.employees["EMP-0001"] = self.employee
        self.preparer = uuid4()
        self.approver = uuid4()
        self.use_cases = OffCyclePayrollUseCases(self.repository, clock=lambda: NOW)

    def _create(self, rows=None):
        return asyncio.run(
            self.use_cases.create_benefit_run(
                CreateOffCycleBenefitRunInput(
                    payroll_group_id=self.group_id,
                    benefit_type_id=self.benefit_type.id,
                    proposed_payment_date=date(2026, 12, 10),
                    actor_id=self.preparer,
                    rows=rows
                    or (OffCycleUploadRow(employee_no="emp-0001", amount=Decimal("10000")),),
                )
            )
        )

    def test_full_approval_flow_with_separation_of_duties(self) -> None:
        run = self._create()
        self.assertEqual(run.status, "DRAFT")
        self.assertEqual(run.lines[0].taxable_amount, Decimal("10000.00"))
        run = asyncio.run(self.use_cases.submit_run(run.id, self.preparer))
        self.assertEqual(run.status, "PENDING")
        with self.assertRaises(PermissionError):
            asyncio.run(self.use_cases.approve_run(run.id, self.preparer))
        run = asyncio.run(self.use_cases.approve_run(run.id, self.approver))
        self.assertEqual(run.status, "APPROVED")
        self.assertEqual(run.approved_by, self.approver)
        run = asyncio.run(
            self.use_cases.mark_run_paid(run.id, self.preparer, date(2026, 12, 12))
        )
        self.assertEqual(run.status, "PAID")
        self.assertEqual(run.actual_payment_date, date(2026, 12, 12))

    def test_recalculation_excludes_own_run_from_ytd(self) -> None:
        run = self._create()
        asyncio.run(self.use_cases.submit_run(run.id, self.preparer))
        last_call = self.repository.ytd_calls[-1]
        self.assertEqual(last_call["exclude_run_id"], run.id)
        self.assertEqual(last_call["created_before"], NOW)

    def test_approval_stops_when_ytd_changed_after_submission(self) -> None:
        run = self._create()
        asyncio.run(self.use_cases.submit_run(run.id, self.preparer))
        self.repository.ytd[self.employee.employee_id] = _ytd(taxable="300000")
        with self.assertRaisesRegex(ValueError, "approve again"):
            asyncio.run(self.use_cases.approve_run(run.id, self.approver))
        refreshed = self.repository.runs[run.id]
        self.assertEqual(refreshed.status, "PENDING")
        self.assertEqual(refreshed.lines[0].withholding_tax, Decimal("1500.00"))
        approved = asyncio.run(self.use_cases.approve_run(run.id, self.approver))
        self.assertEqual(approved.status, "APPROVED")

    def test_upload_reports_unknown_and_duplicate_employees(self) -> None:
        with self.assertRaisesRegex(ValueError, "more than once"):
            self._create(
                rows=(
                    OffCycleUploadRow(employee_no="EMP-0001", amount=Decimal("1")),
                    OffCycleUploadRow(employee_no="emp-0001", amount=Decimal("2")),
                )
            )
        with self.assertRaisesRegex(ValueError, "EMP-9999"):
            self._create(rows=(OffCycleUploadRow(employee_no="EMP-9999", amount=Decimal("1")),))

    def test_non_cash_benefit_type_is_rejected(self) -> None:
        self.repository.benefit_type = _benefit_type(
            payroll_group_id=self.group_id, category="NON_CASH"
        )
        with self.assertRaisesRegex(ValueError, "cash benefits"):
            self._create()

    def test_reject_requires_reason(self) -> None:
        run = self._create()
        asyncio.run(self.use_cases.submit_run(run.id, self.preparer))
        with self.assertRaisesRegex(ValueError, "reason"):
            asyncio.run(self.use_cases.reject_run(run.id, self.approver, "  "))
        rejected = asyncio.run(self.use_cases.reject_run(run.id, self.approver, "Wrong amounts"))
        self.assertEqual(rejected.status, "REJECTED")
        self.assertEqual(rejected.rejection_reason, "Wrong amounts")

    def test_thirteenth_month_run_requires_exempt_limited_bonus_type(self) -> None:
        payable = ThirteenthMonthPayable(
            result_id=uuid4(),
            employee_id=self.employee.employee_id,
            employee_no="EMP-0001",
            employee_name="Juan Dela Cruz",
            amount=Decimal("20000"),
        )
        self.repository.payables = [payable]
        data = CreateThirteenthMonthOffCycleRunInput(
            payroll_group_id=self.group_id,
            benefit_type_id=self.benefit_type.id,
            thirteenth_month_run_id=uuid4(),
            proposed_payment_date=date(2026, 12, 15),
            actor_id=self.preparer,
        )
        with self.assertRaisesRegex(ValueError, "Exempt up to limit"):
            asyncio.run(self.use_cases.create_thirteenth_month_run(data))

        self.repository.benefit_type = _benefit_type(
            payroll_group_id=self.group_id, tax_treatment="EXEMPT_LIMITED", code="13TH"
        )
        self.repository.ytd[self.employee.employee_id] = _ytd(taxable="300000")
        run = asyncio.run(self.use_cases.create_thirteenth_month_run(data))
        line = run.lines[0]
        self.assertEqual(line.thirteenth_month_result_id, payable.result_id)
        self.assertEqual(line.exempt_limited_amount, Decimal("20000.00"))
        # Cumulative method: 15% of (300,000 - 250,000) not yet withheld.
        self.assertEqual(line.withholding_tax, Decimal("7500.00"))


if __name__ == "__main__":
    unittest.main()
