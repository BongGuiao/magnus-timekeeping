import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.attendance.application.use_case import (
    calculate_break_policy,
    calculate_net_nonpayable_break_minutes,
)
from app.attendance.domain.worked_minutes import (
    net_worked_minutes,
    requires_scheduled_work,
    scheduled_work_minutes,
)
from app.attendance.domain.entities.attendance import AttendanceEntity


class WorkedMinutesTests(unittest.TestCase):
    def test_scheduled_work_minutes_excludes_lateness_and_undertime(self) -> None:
        self.assertEqual(scheduled_work_minutes(480, 0, 0), 480)
        self.assertEqual(scheduled_work_minutes(480, 15, 0), 465)
        self.assertEqual(scheduled_work_minutes(480, 15, 20), 445)
        self.assertEqual(scheduled_work_minutes(480, 300, 240), 0)
        self.assertEqual(scheduled_work_minutes(480, 0, 0, "REST", "REG"), 0)
        self.assertEqual(scheduled_work_minutes(480, 0, 0, "REG", "SNW"), 0)
        self.assertEqual(scheduled_work_minutes(480, 0, 0, "REG", "SWH"), 480)
        self.assertFalse(requires_scheduled_work("REST", "REG"))
        self.assertFalse(requires_scheduled_work("REG", "RH"))
        self.assertTrue(requires_scheduled_work("REG", "SWH"))
        self.assertIsNone(scheduled_work_minutes(None, 0, 0))

    def test_dashboard_matches_existing_attendance_break_formula(self) -> None:
        start = datetime(2026, 10, 12, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=9)
        for segment_type, allowance, duration, auto_deduct, expected_minutes in [
            ("PAID_BREAK", 15, 15, False, 540),
            ("PAID_BREAK", 15, 21, False, 534),
            ("UNPAID_BREAK", 60, 75, False, 465),
            ("UNPAID_BREAK", 60, None, True, 480),
            ("UNPAID_BREAK", 60, 70, True, 470),
            ("UNPAID_BREAK", 60, 30, False, 480),
        ]:
            with self.subTest(segment_type=segment_type, duration=duration, auto_deduct=auto_deduct):
                record = AttendanceEntity(user_id=uuid4(), work_date=start.date())
                rule = {
                    "break_slot": "MEAL_BREAK",
                    "segment_type": segment_type,
                    "break_minutes": allowance,
                    "auto_deduct": auto_deduct,
                }
                if duration is not None:
                    record.meal_break_out_at = start + timedelta(hours=4)
                    record.meal_break_in_at = record.meal_break_out_at + timedelta(minutes=duration)
                _, _, intervals = calculate_break_policy(record, [rule])
                saved_deduction = calculate_net_nonpayable_break_minutes(
                    record,
                    [rule],
                    intervals,
                    start,
                    end,
                )
                self.assertEqual(
                    net_worked_minutes(start, end, {
                        "break_calculation": {"net_nonpayable_minutes": saved_deduction},
                    }),
                    expected_minutes,
                )

    def test_net_minutes_deduct_only_nonpayable_breaks(self) -> None:
        start = datetime(2026, 10, 12, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=9, seconds=59)
        self.assertEqual(net_worked_minutes(start, end, None), 540)
        self.assertEqual(
            net_worked_minutes(start, end, {
                "break_calculation": {"net_nonpayable_minutes": 60},
            }),
            480,
        )
        self.assertEqual(
            net_worked_minutes(start, end, {
                "break_calculation": {"net_nonpayable_minutes": 600},
            }),
            0,
        )

    def test_incomplete_or_reversed_punches_have_no_worked_minutes(self) -> None:
        start = datetime(2026, 10, 12, tzinfo=timezone.utc)
        self.assertIsNone(net_worked_minutes(None, start, None))
        self.assertIsNone(net_worked_minutes(start, None, None))
        self.assertIsNone(net_worked_minutes(start, start - timedelta(minutes=1), None))
        self.assertEqual(net_worked_minutes(start, start, None), 0)

    def test_overnight_and_offset_punches_use_full_elapsed_time(self) -> None:
        start = datetime.fromisoformat("2026-10-12T22:00:00+08:00")
        end = datetime.fromisoformat("2026-10-12T22:00:00+00:00")
        self.assertEqual(
            net_worked_minutes(start, end, {
                "break_calculation": {"net_nonpayable_minutes": 30},
            }),
            450,
        )
