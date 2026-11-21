import unittest
from datetime import date, timedelta

from app.attendance.domain.return_to_work_screening import (
    ReviewDay,
    ReviewDayStatus,
    current_absence_evidence,
)


class ReturnToWorkScreeningTests(unittest.TestCase):
    def days(self, *statuses):
        today = date(2026, 11, 20)
        return [
            ReviewDay(today - timedelta(days=offset), status)
            for offset, status in enumerate(statuses)
        ]

    def test_three_marked_workdays_across_rest_days_and_holidays(self):
        result = current_absence_evidence(self.days(
            ReviewDayStatus.ABSENT,
            ReviewDayStatus.HOLIDAY,
            ReviewDayStatus.REST_DAY,
            ReviewDayStatus.ABSENT,
            ReviewDayStatus.ABSENT,
        ))
        self.assertEqual(result, (date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 20)))

    def test_leave_business_presence_or_unknown_interrupt_a_streak(self):
        for interruption in (
            ReviewDayStatus.APPROVED_LEAVE,
            ReviewDayStatus.APPROVED_BUSINESS,
            ReviewDayStatus.PRESENT,
            ReviewDayStatus.UNKNOWN,
        ):
            with self.subTest(interruption=interruption):
                result = current_absence_evidence(self.days(
                    ReviewDayStatus.ABSENT,
                    ReviewDayStatus.ABSENT,
                    interruption,
                    ReviewDayStatus.ABSENT,
                ))
                self.assertEqual(result, ())

    def test_missing_or_unordered_days_are_rejected(self):
        for dates in ((20, 18), (20, 20), (19, 20)):
            with self.subTest(dates=dates):
                with self.assertRaises(ValueError):
                    current_absence_evidence([
                        ReviewDay(date(2026, 11, day), ReviewDayStatus.ABSENT)
                        for day in dates
                    ])

    def test_fewer_than_three_marked_days_do_not_qualify(self):
        self.assertEqual(current_absence_evidence(self.days(
            ReviewDayStatus.ABSENT, ReviewDayStatus.REST_DAY, ReviewDayStatus.ABSENT,
        )), ())


if __name__ == "__main__":
    unittest.main()
