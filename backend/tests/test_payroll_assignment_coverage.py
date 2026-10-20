import unittest
from datetime import date

from app.payroll.domain.assignment_coverage import require_exact_assignment_coverage


class PayrollAssignmentCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.period_start = date(2026, 1, 1)
        self.period_end = date(2026, 1, 31)

    def test_accepts_one_assignment_covering_full_compensation_period(self) -> None:
        require_exact_assignment_coverage(
            self.period_start,
            self.period_end,
            [(date(2025, 12, 1), date(2026, 2, 1), None)],
        )

    def test_accepts_contiguous_assignments_covering_period(self) -> None:
        require_exact_assignment_coverage(
            self.period_start,
            self.period_end,
            [
                (self.period_start, date(2026, 1, 15), None),
                (date(2026, 1, 16), self.period_end, None),
            ],
        )

    def test_rejects_gap_between_assignments(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one active employment assignment"):
            require_exact_assignment_coverage(
                self.period_start,
                self.period_end,
                [
                    (self.period_start, date(2026, 1, 14), None),
                    (date(2026, 1, 16), self.period_end, None),
                ],
            )

    def test_rejects_overlapping_assignments(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one active employment assignment"):
            require_exact_assignment_coverage(
                self.period_start,
                self.period_end,
                [
                    (self.period_start, date(2026, 1, 16), None),
                    (date(2026, 1, 16), self.period_end, None),
                ],
            )

    def test_open_ended_compensation_requires_open_ended_assignment_coverage(self) -> None:
        require_exact_assignment_coverage(
            self.period_start,
            None,
            [(self.period_start, None, None)],
        )
        with self.assertRaisesRegex(ValueError, "exactly one active employment assignment"):
            require_exact_assignment_coverage(
                self.period_start,
                None,
                [(self.period_start, None, date(2026, 1, 31))],
            )

    def test_separation_date_limits_assignment_coverage(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one active employment assignment"):
            require_exact_assignment_coverage(
                self.period_start,
                self.period_end,
                [(self.period_start, None, date(2026, 1, 30))],
            )


if __name__ == "__main__":
    unittest.main()
