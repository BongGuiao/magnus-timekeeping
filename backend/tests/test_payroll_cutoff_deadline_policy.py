import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.filemaintenance.payroll_cutoffs.application.deadline_policy import (
    CutoffDeadlineError,
    is_cutoff_closed,
    require_attendance_open,
    require_cutoff_open,
    validate_attendance_deadline,
)

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def make_cutoff(**changes):
    values = {
        "id": uuid4(),
        "cutoff_code": "OCT-1",
        "period_start": date(2026, 10, 1),
        "period_end": date(2026, 10, 15),
        "attendance_deadline": None,
        "locked_at": None,
        "status": "ACTIVE",
    }
    values.update(changes)
    return SimpleNamespace(**values)


class DeadlinePolicyTests(unittest.TestCase):
    def test_expired_attendance_deadline_closes_cutoff(self):
        cutoff = make_cutoff(attendance_deadline=datetime(2026, 10, 16, 11, tzinfo=timezone.utc))

        self.assertTrue(is_cutoff_closed(cutoff, NOW))
        with self.assertRaisesRegex(CutoffDeadlineError, "attendance deadline for payroll cutoff OCT-1"):
            require_cutoff_open(cutoff, NOW)

    def test_deadline_is_open_at_exact_time_and_null_deadline_is_unrestricted(self):
        require_cutoff_open(make_cutoff(attendance_deadline=NOW), NOW)
        require_cutoff_open(make_cutoff(), NOW)
        require_cutoff_open(None, NOW)

    def test_approved_cutoff_is_closed_even_before_deadline(self):
        cutoff = make_cutoff(
            attendance_deadline=datetime(2026, 10, 20, tzinfo=timezone.utc),
            locked_at=NOW,
            status="LOCKED",
        )

        with self.assertRaisesRegex(CutoffDeadlineError, "already approved"):
            require_cutoff_open(cutoff, NOW)

    def test_deadline_cannot_close_before_last_cutoff_day_ends(self):
        # Oct 15 23:59 Manila is still within the cutoff's last day.
        with self.assertRaises(ValueError):
            validate_attendance_deadline(
                date(2026, 10, 15), datetime(2026, 10, 15, 15, 59, tzinfo=timezone.utc)
            )
        validate_attendance_deadline(date(2026, 10, 15), datetime(2026, 10, 15, 16, tzinfo=timezone.utc))
        validate_attendance_deadline(date(2026, 10, 15), None)


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


class AttendanceRangeDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_cutoffs_overlapping_the_request_and_assignment_are_checked(self):
        covered = make_cutoff(
            attendance_deadline=datetime(2026, 10, 16, 11, tzinfo=timezone.utc),
        )
        outside_cutoff = make_cutoff(
            id=uuid4(),
            cutoff_code="SEP-2",
            period_start=date(2026, 9, 16),
            period_end=date(2026, 9, 30),
            attendance_deadline=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        assignment = SimpleNamespace(
            effective_from=date(2026, 9, 1),
            effective_to=None,
            separation_date=None,
        )
        session = FakeSession([(covered, assignment), (outside_cutoff, assignment)])

        with self.assertRaisesRegex(CutoffDeadlineError, "OCT-1"):
            await require_attendance_open(
                session,
                uuid4(),
                date(2026, 10, 10),
                date(2026, 10, 12),
                NOW,
            )

    async def test_request_with_no_matching_cutoff_remains_unrestricted(self):
        session = FakeSession([])

        await require_attendance_open(
            session,
            uuid4(),
            date(2026, 10, 10),
            date(2026, 10, 12),
            NOW,
        )

    async def test_leave_in_next_cutoff_is_not_blocked_by_expired_previous_cutoff(self):
        previous_cutoff = make_cutoff(
            cutoff_code="OCT-1",
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 15),
            attendance_deadline=datetime(2026, 10, 15, 23, tzinfo=timezone.utc),
        )
        next_cutoff = make_cutoff(
            id=uuid4(),
            cutoff_code="OCT-2",
            period_start=date(2026, 10, 16),
            period_end=date(2026, 10, 31),
            attendance_deadline=datetime(2026, 10, 30, 23, tzinfo=timezone.utc),
        )
        assignment = SimpleNamespace(
            effective_from=date(2026, 9, 1),
            effective_to=None,
            separation_date=None,
        )

        await require_attendance_open(
            FakeSession([(previous_cutoff, assignment), (next_cutoff, assignment)]),
            uuid4(),
            date(2026, 10, 20),
            date(2026, 10, 21),
            NOW,
        )
