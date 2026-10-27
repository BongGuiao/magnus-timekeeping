import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.payroll.infrastructure.db_model import GrossPayResultModel
from app.payroll.infrastructure.repository import _prior_first_half_contributions


class PriorFirstHalfContributionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.employee_id = uuid4()
        self.other_employee_id = uuid4()
        self.cutoff = PayrollCutoffModel(
            id=uuid4(),
            payroll_group_id=uuid4(),
            cutoff_half="SECOND_HALF",
            period_start=date(2026, 10, 16),
            period_end=date(2026, 10, 31),
        )
        self.session = SimpleNamespace(scalars=AsyncMock(return_value=[]))

    async def test_first_half_ignores_previous_payroll_without_querying_or_deleting_it(self) -> None:
        self.cutoff.cutoff_half = "FIRST_HALF"
        employee, employer = await _prior_first_half_contributions(
            self.session, self.cutoff, [self.employee_id]
        )
        self.session.scalars.assert_not_awaited()
        self.assertEqual(employee[self.employee_id], {
            "SSS": Decimal(0), "PHILHEALTH": Decimal(0), "PAGIBIG": Decimal(0),
        })
        self.assertEqual(employer[self.employee_id], employee[self.employee_id])

    async def test_second_half_selects_latest_preceding_first_half_across_months(self) -> None:
        self.cutoff.period_start = date(2026, 11, 1)
        self.cutoff.period_end = date(2026, 11, 15)
        employee, employer = await _prior_first_half_contributions(
            self.session, self.cutoff, [self.employee_id]
        )
        statement = self.session.scalars.call_args.args[0]
        sql = " ".join(str(statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
        )).split())
        for predicate in (
            "payroll.gross_pay_runs.is_current IS true",
            f"payroll.gross_pay_results.employee_id IN ('{self.employee_id}')",
            "payroll.gross_pay_results.status = 'READY'",
            f"payroll.cutoffs.payroll_group_id = '{self.cutoff.payroll_group_id}'",
            "payroll.cutoffs.is_active IS true",
            "payroll.cutoffs.cutoff_half = 'FIRST_HALF'",
            "payroll.cutoffs.period_end < '2026-11-01'",
            f"payroll.cutoffs.id != '{self.cutoff.id}'",
            "ORDER BY payroll.cutoffs.period_end DESC, payroll.cutoffs.period_start DESC",
        ):
            with self.subTest(predicate=predicate):
                self.assertIn(predicate, sql)
        self.assertNotIn("payroll.cutoffs.period_end >=", sql)
        self.assertNotIn("payroll.cutoffs.period_end <=", sql)
        self.assertEqual(employee[self.employee_id]["SSS"], Decimal(0))
        self.assertEqual(employer[self.employee_id]["SSS"], Decimal(0))

    async def test_latest_saved_first_half_per_employee_is_not_added_to_older_results(self) -> None:
        def saved_result(employee_id, employee_amount, employer_amount):
            return GrossPayResultModel(
                employee_id=employee_id,
                contribution_lines=[
                    {
                        "program_code": program,
                        "employee_amount": employee_amount,
                        "employer_amount": employer_amount,
                    }
                    for program in ("SSS", "PHILHEALTH", "PAGIBIG")
                ],
            )

        self.session.scalars.return_value = [
            saved_result(self.employee_id, "560.00", "1150.00"),
            saved_result(self.other_employee_id, "100.00", "200.00"),
            saved_result(self.employee_id, "999.00", "999.00"),
        ]
        missing_employee_id = uuid4()
        employee, employer = await _prior_first_half_contributions(
            self.session, self.cutoff,
            [self.employee_id, self.other_employee_id, missing_employee_id],
        )
        for program in ("SSS", "PHILHEALTH", "PAGIBIG"):
            self.assertEqual(employee[self.employee_id][program], Decimal("560"))
            self.assertEqual(employer[self.employee_id][program], Decimal("1150"))
            self.assertEqual(employee[self.other_employee_id][program], Decimal("100"))
            self.assertEqual(employer[self.other_employee_id][program], Decimal("200"))
            self.assertEqual(employee[missing_employee_id][program], Decimal(0))
            self.assertEqual(employer[missing_employee_id][program], Decimal(0))
