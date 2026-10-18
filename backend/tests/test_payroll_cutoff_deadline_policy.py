import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.filemaintenance.payroll_cutoffs.application.deadline_policy import (
    CutoffDeadlineError,
    require_cutoff_phase_open,
    require_employee_phase_open,
)

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def make_cutoff(**changes):
    values = {
        "id": uuid4(),
        "cutoff_code": "OCT-1",
        "period_start": date(2026, 10, 1),
        "period_end": date(2026, 10, 15),
        "employee_review_deadline": None,
        "supervisor_deadline": None,
        "hr_deadline": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


class DeadlinePolicyTests(unittest.TestCase):
    def test_each_phase_uses_its_own_deadline(self):
        cutoff = make_cutoff(
            employee_review_deadline=datetime(2026, 10, 16, 11, tzinfo=timezone.utc),
            supervisor_deadline=datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
            hr_deadline=datetime(2026, 10, 16, 13, tzinfo=timezone.utc),
        )

        with self.assertRaisesRegex(CutoffDeadlineError, "employee filing deadline"):
            require_cutoff_phase_open(cutoff, "EMPLOYEE", NOW)
        require_cutoff_phase_open(cutoff, "SUPERVISOR", NOW)
        require_cutoff_phase_open(cutoff, "HR", NOW)

    def test_deadline_is_open_at_exact_time_and_null_deadline_is_unrestricted(self):
        cutoff = make_cutoff(
            employee_review_deadline=NOW,
            supervisor_deadline=None,
            hr_deadline=None,
        )

        require_cutoff_phase_open(cutoff, "EMPLOYEE", NOW)
        require_cutoff_phase_open(cutoff, "SUPERVISOR", NOW)
        require_cutoff_phase_open(cutoff, "HR", NOW)

    def test_expired_hr_deadline_is_rejected(self):
        cutoff = make_cutoff(
            hr_deadline=datetime(2026, 10, 16, 11, tzinfo=timezone.utc),
        )

        with self.assertRaisesRegex(CutoffDeadlineError, "HR processing deadline"):
            require_cutoff_phase_open(cutoff, "HR", NOW)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, statement):
        self.statement = statement
        return FakeResult(self.rows)


class EmployeeDateRangeDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_cutoffs_overlapping_the_request_and_assignment_are_checked(self):
        covered = make_cutoff(
            employee_review_deadline=datetime(2026, 10, 16, 11, tzinfo=timezone.utc),
        )
        outside_cutoff = make_cutoff(
            id=uuid4(),
            cutoff_code="SEP-2",
            period_start=date(2026, 9, 16),
            period_end=date(2026, 9, 30),
            employee_review_deadline=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        assignment = SimpleNamespace(
            effective_from=date(2026, 9, 1),
            effective_to=None,
            separation_date=None,
        )
        session = FakeSession([(covered, assignment), (outside_cutoff, assignment)])

        with self.assertRaisesRegex(CutoffDeadlineError, "OCT-1"):
            await require_employee_phase_open(
                session,
                uuid4(),
                date(2026, 10, 10),
                date(2026, 10, 12),
                "EMPLOYEE",
                NOW,
            )

    async def test_request_with_no_matching_cutoff_remains_unrestricted(self):
        session = FakeSession([])

        await require_employee_phase_open(
            session,
            uuid4(),
            date(2026, 10, 10),
            date(2026, 10, 12),
            "EMPLOYEE",
            NOW,
        )

    async def test_leave_in_next_cutoff_is_not_blocked_by_expired_previous_cutoff(self):
        previous_cutoff = make_cutoff(
            cutoff_code="OCT-1",
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 15),
            employee_review_deadline=datetime(2026, 10, 15, 23, tzinfo=timezone.utc),
        )
        next_cutoff = make_cutoff(
            id=uuid4(),
            cutoff_code="OCT-2",
            period_start=date(2026, 10, 16),
            period_end=date(2026, 10, 31),
            employee_review_deadline=datetime(2026, 10, 30, 23, tzinfo=timezone.utc),
        )
        assignment = SimpleNamespace(
            effective_from=date(2026, 9, 1),
            effective_to=None,
            separation_date=None,
        )

        await require_employee_phase_open(
            FakeSession([(previous_cutoff, assignment), (next_cutoff, assignment)]),
            uuid4(),
            date(2026, 10, 20),
            date(2026, 10, 21),
            "EMPLOYEE",
            NOW,
        )
