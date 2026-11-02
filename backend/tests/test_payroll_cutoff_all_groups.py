import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.filemaintenance.payroll_cutoffs.application.use_case import (
    CreatePayrollCutoffsForCompanyUseCase,
    PayrollCutoffConflictError,
    PayrollCutoffReferenceError,
    _translate_integrity_error,
)


class FakeCutoffRepository:
    def __init__(self):
        self.added = []
        self.fail_on_add = None

    async def add(self, cutoff):
        if self.fail_on_add == len(self.added):
            raise ValueError("cutoff insert failed")
        self.added.append(cutoff)
        cutoff.id = uuid4()
        return cutoff


class FakeUnitOfWork:
    def __init__(self, groups):
        self.groups = groups
        self.repository = FakeCutoffRepository()
        self.session = SimpleNamespace(
            scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: groups)),
        )
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.rolled_back = exc_type is not None

    def get_repo(self, entity_class, model_class):
        return self.repository


class CreatePayrollCutoffsForCompanyTests(unittest.IsolatedAsyncioTestCase):
    def _payload(self):
        return {
            "cutoff_code": "ALL-GROUPS-20261101-20261115",
            "cutoff_half": "FIRST_HALF",
            "period_start": date(2026, 11, 1),
            "period_end": date(2026, 11, 15),
            "pay_date": date(2026, 11, 20),
            "attendance_deadline": None,
            "employee_filing_deadline": None,
            "status": "SCHEDULED",
            "calculation_version": None,
            "export_batch_id": None,
            "is_active": True,
            "created_by": uuid4(),
            "updated_by": uuid4(),
        }

    async def test_creates_identical_cutoffs_for_every_active_group(self):
        groups = [
            SimpleNamespace(id=uuid4(), payroll_group_code=code)
            for code in ("OFFICE", "FIELD")
        ]
        uow = FakeUnitOfWork(groups)
        results = await CreatePayrollCutoffsForCompanyUseCase(uow).execute(
            uuid4(), self._payload(),
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(
            [result.payroll_group_id for result in results],
            [group.id for group in groups],
        )
        self.assertEqual(
            {result.cutoff_code for result in results},
            {"ALL-GROUPS-20261101-20261115"},
        )
        self.assertEqual(
            {(result.period_start, result.period_end, result.pay_date) for result in results},
            {(date(2026, 11, 1), date(2026, 11, 15), date(2026, 11, 20))},
        )
        self.assertFalse(uow.rolled_back)
        statement = uow.session.scalars.await_args.args[0]
        self.assertTrue(statement.compile().params)

    async def test_no_active_groups_is_an_explicit_error(self):
        uow = FakeUnitOfWork([])
        with self.assertRaisesRegex(PayrollCutoffReferenceError, "No active payroll groups"):
            await CreatePayrollCutoffsForCompanyUseCase(uow).execute(
                uuid4(), self._payload(),
            )
        self.assertTrue(uow.rolled_back)

    async def test_insert_failure_rolls_back_the_batch(self):
        uow = FakeUnitOfWork([
            SimpleNamespace(id=uuid4(), payroll_group_code="OFFICE"),
            SimpleNamespace(id=uuid4(), payroll_group_code="FIELD"),
        ])
        uow.repository.fail_on_add = 1

        with self.assertRaisesRegex(ValueError, "cutoff insert failed"):
            await CreatePayrollCutoffsForCompanyUseCase(uow).execute(
                uuid4(), self._payload(),
            )
        self.assertTrue(uow.rolled_back)


class PayrollCutoffIntegrityErrorTests(unittest.TestCase):
    def test_asyncpg_duplicate_code_is_translated_to_conflict(self):
        error = IntegrityError(
            "INSERT INTO payroll.cutoffs ...",
            {},
            SimpleNamespace(
                constraint_name="cutoffs_payroll_group_id_cutoff_code_key",
            ),
        )

        with self.assertRaisesRegex(
            PayrollCutoffConflictError,
            "A cutoff with this code already exists",
        ):
            _translate_integrity_error(error)


if __name__ == "__main__":
    unittest.main()
