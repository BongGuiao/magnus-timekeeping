import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.payroll.domain.entities.gross_payroll import PayrollApprovalPermissionError
from app.payroll.infrastructure.repository import SqlAlchemyPayrollRepository


class FakeResultRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, scalar_rows=(), result_rows=()):
        self.scalar_rows = list(scalar_rows)
        self.result_rows = list(result_rows)

    async def scalar(self, statement):
        return self.scalar_rows.pop(0)

    async def scalars(self, statement):
        return FakeResultRows(self.result_rows.pop(0))


class FakeUnitOfWork:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class PayrollCutoffApprovalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cutoff_id = uuid4()
        self.employee_id = uuid4()
        self.cutoff_result_id = uuid4()
        self.actor_id = uuid4()
        self.cutoff = SimpleNamespace(
            id=self.cutoff_id,
            is_active=True,
            locked_at=None,
            locked_by=None,
            status="ACTIVE",
            attendance_deadline=datetime.now(timezone.utc) - timedelta(hours=1),
            updated_at=None,
            updated_by=None,
            row_version=1,
        )
        self.run = SimpleNamespace(id=uuid4(), calculated_by=uuid4())
        self.payroll_result = SimpleNamespace(
            employee_id=self.employee_id,
            cutoff_result_id=self.cutoff_result_id,
            status="READY",
        )
        self.time_result = SimpleNamespace(
            id=self.cutoff_result_id,
            employee_id=self.employee_id,
            incomplete_time_source_count=0,
        )

    def repository(self, *, payroll_results=None, time_results=None):
        session = FakeSession(
            scalar_rows=(self.cutoff, self.run),
            result_rows=(
                [self.payroll_result] if payroll_results is None else payroll_results,
                [self.time_result] if time_results is None else time_results,
            ),
        )
        return SqlAlchemyPayrollRepository(FakeUnitOfWork(session))

    async def test_approval_locks_cutoff_when_all_results_are_ready(self):
        approved_at = datetime.now(timezone.utc)
        result = await self.repository().approve_payroll_cutoff(
            self.cutoff_id,
            self.actor_id,
            approved_at,
        )

        self.assertTrue(result.locked)
        self.assertEqual(result.locked_at, approved_at)
        self.assertEqual(result.locked_by, self.actor_id)
        self.assertEqual(self.cutoff.status, "LOCKED")

    async def test_approval_rejects_any_held_employee_result(self):
        self.payroll_result.status = "HOLD"

        with self.assertRaisesRegex(ValueError, "All employee payroll results must be READY"):
            await self.repository().approve_payroll_cutoff(
                self.cutoff_id,
                self.actor_id,
                datetime.now(timezone.utc),
            )

        self.assertIsNone(self.cutoff.locked_at)

    async def test_approval_rejects_changed_time_results(self):
        self.time_result.id = uuid4()

        with self.assertRaisesRegex(ValueError, "Attendance results changed"):
            await self.repository().approve_payroll_cutoff(
                self.cutoff_id,
                self.actor_id,
                datetime.now(timezone.utc),
            )

        self.assertIsNone(self.cutoff.locked_at)

    async def test_approval_waits_for_attendance_deadline(self):
        self.cutoff.attendance_deadline = datetime.now(timezone.utc) + timedelta(hours=1)

        with self.assertRaisesRegex(ValueError, "after the cutoff's attendance deadline"):
            await self.repository().approve_payroll_cutoff(
                self.cutoff_id,
                self.actor_id,
                datetime.now(timezone.utc),
            )

        self.assertIsNone(self.cutoff.locked_at)

    async def test_approval_requires_attendance_deadline(self):
        self.cutoff.attendance_deadline = None

        with self.assertRaisesRegex(ValueError, "Set the cutoff's attendance deadline"):
            await self.repository().approve_payroll_cutoff(
                self.cutoff_id,
                self.actor_id,
                datetime.now(timezone.utc),
            )

    async def test_calculator_cannot_approve_own_payroll(self):
        self.run.calculated_by = self.actor_id

        with self.assertRaises(PayrollApprovalPermissionError):
            await self.repository().approve_payroll_cutoff(
                self.cutoff_id,
                self.actor_id,
                datetime.now(timezone.utc),
            )

        self.assertIsNone(self.cutoff.locked_at)

    async def test_admin_unlock_clears_lock_and_reopens_cutoff(self):
        self.cutoff.locked_at = datetime.now(timezone.utc)
        self.cutoff.locked_by = self.actor_id
        self.cutoff.status = "LOCKED"
        session = FakeSession(scalar_rows=(self.cutoff,))
        repository = SqlAlchemyPayrollRepository(FakeUnitOfWork(session))

        result = await repository.unlock_payroll_cutoff(
            self.cutoff_id,
            self.actor_id,
            datetime.now(timezone.utc),
        )

        self.assertFalse(result.locked)
        self.assertIsNone(self.cutoff.locked_at)
        self.assertIsNone(self.cutoff.locked_by)
        self.assertEqual(self.cutoff.status, "ACTIVE")


if __name__ == "__main__":
    unittest.main()
