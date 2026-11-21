import unittest
from datetime import date
from uuid import uuid4

from app.attendance.domain.tardiness_screening import (
    AttendanceDayFact,
    previous_calendar_month,
    screen_tardiness,
)


class TardinessScreeningTests(unittest.TestCase):
    def test_previous_month_handles_year_boundary_and_leap_year(self):
        self.assertEqual(previous_calendar_month(date(2027, 1, 1)), (date(2026, 12, 1), date(2026, 12, 31)))
        self.assertEqual(previous_calendar_month(date(2028, 3, 1)), (date(2028, 2, 1), date(2028, 2, 29)))

    def test_counts_dates_not_records_and_reports_unresolved_items(self):
        employee = uuid4()
        other = uuid4()
        facts = [
            AttendanceDayFact(employee, date(2026, 11, day), uuid4(), 5)
            for day in (1, 2, 3, 4)
        ]
        facts.append(AttendanceDayFact(employee, date(2026, 11, 1), uuid4(), 10))
        facts.append(AttendanceDayFact(employee, date(2026, 10, 31), uuid4(), 5))
        facts.append(AttendanceDayFact(other, date(2026, 11, 1), uuid4(), 5))
        results = screen_tardiness(
            facts, [(employee, date(2026, 11, 9)), (employee, date(2026, 12, 1))],
            date(2026, 11, 1), date(2026, 11, 30),
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].employee_id, employee)
        self.assertEqual(results[0].late_dates, tuple(date(2026, 11, day) for day in (1, 2, 3, 4)))
        self.assertEqual(results[0].duplicate_dates, (date(2026, 11, 1),))
        self.assertEqual(results[0].pending_correction_dates, (date(2026, 11, 9),))

    def test_three_late_dates_with_duplicate_do_not_meet_threshold(self):
        employee = uuid4()
        facts = [
            AttendanceDayFact(employee, date(2026, 11, day), uuid4(), 5)
            for day in (1, 1, 2, 3)
        ]
        self.assertEqual(screen_tardiness(facts, [], date(2026, 11, 1), date(2026, 11, 30)), [])


if __name__ == "__main__":
    unittest.main()
