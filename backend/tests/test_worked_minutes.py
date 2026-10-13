import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.attendance.application.use_case import calculate_break_policy, _net_interval_seconds
from app.attendance.application.worked_minutes import net_worked_minutes
from app.attendance.domain.entities.attendance import AttendanceEntity


class WorkedMinutesTests(unittest.TestCase):
    def test_dashboard_matches_existing_attendance_break_formula(self) -> None:
        start = datetime(2026, 10, 12, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=9)
        for segment_type, allowance, duration, auto_deduct, expected_minutes in [
            ("PAID_BREAK", 15, 15, False, 540),
            ("PAID_BREAK", 15, 21, False, 534),
            ("UNPAID_BREAK", 60, 75, False, 465),
            ("UNPAID_BREAK", 60, None, True, 480),
            ("UNPAID_BREAK", 60, 70, True, 470),
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
                gross_seconds = (end - start).total_seconds()
                deducted_seconds = gross_seconds - _net_interval_seconds(start, end, intervals)
                auto_minutes = allowance if segment_type == "UNPAID_BREAK" and auto_deduct and duration is None else 0
                saved_deduction = min(int(gross_seconds // 60), int(deducted_seconds // 60) + auto_minutes)
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
