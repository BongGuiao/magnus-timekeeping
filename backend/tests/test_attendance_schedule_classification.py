import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from uuid import UUID

from app.attendance.application.use_case import (
    calculate_attendance_metrics,
    calculate_night_differential_minutes,
    calculate_overtime_breakdown,
    get_cycle_day_number,
    get_unpaid_break_intervals,
)
from app.attendance.domain.entities.attendance import AttendanceEntity
from app.attendance.infrastructure.db_model import AttendanceModel, OvertimeApplicationModel


class AttendanceScheduleClassificationTests(unittest.TestCase):
    def test_attendance_schedule_template_reference_is_nullable(self) -> None:
        column = AttendanceModel.__table__.c.schedule_template_id

        self.assertTrue(column.nullable)
        foreign_key = next(iter(column.foreign_keys))
        self.assertEqual(foreign_key.target_fullname, "schedule.schedule_templates.id")
        self.assertEqual(foreign_key.ondelete, "SET NULL")

    def test_overtime_application_model_links_to_attendance_record_and_employee(self) -> None:
        table = OvertimeApplicationModel.__table__

        self.assertEqual(table.schema, "attendance")
        self.assertIn("attendance_date", table.c)
        self.assertIn("requested_minutes", table.c)
        self.assertIn("supervisor_approved_minutes", table.c)
        foreign_key_targets = {
            foreign_key.target_fullname
            for column in table.c
            for foreign_key in column.foreign_keys
        }
        self.assertIn("attendance.attendance_records.id", foreign_key_targets)
        self.assertIn("hr.employees.id", foreign_key_targets)

    def test_assignment_effective_date_is_cycle_day_one(self) -> None:
        effective_from = date(2026, 10, 9)

        self.assertEqual(
            get_cycle_day_number(effective_from, effective_from, 10),
            1,
        )

    def test_cycle_day_wraps_after_cycle_length(self) -> None:
        effective_from = date(2026, 10, 9)

        self.assertEqual(
            get_cycle_day_number(effective_from, date(2026, 10, 19), 10),
            1,
        )

    def test_weekly_pattern_follows_calendar_week(self) -> None:
        effective_from = date(2026, 1, 1)

        self.assertEqual(get_cycle_day_number(effective_from, date(2026, 10, 5), 7), 1)
        self.assertEqual(get_cycle_day_number(effective_from, date(2026, 10, 10), 7), 6)
        self.assertEqual(get_cycle_day_number(effective_from, date(2026, 10, 11), 7), 7)

    def test_work_date_before_assignment_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot precede"):
            get_cycle_day_number(date(2026, 10, 9), date(2026, 10, 8), 7)

    def test_nonpositive_cycle_length_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one day"):
            get_cycle_day_number(date(2026, 10, 9), date(2026, 10, 9), 0)

    def test_lateness_applies_schedule_grace_period(self) -> None:
        late, undertime, overtime = calculate_attendance_metrics(
            expected_clock_in_at=datetime(2026, 10, 9, 1, tzinfo=timezone.utc),
            expected_clock_out_at=datetime(2026, 10, 9, 10, tzinfo=timezone.utc),
            actual_clock_in_at=datetime(2026, 10, 9, 1, 15, tzinfo=timezone.utc),
            actual_clock_out_at=None,
            grace_minutes=10,
        )

        self.assertEqual((late, undertime, overtime), (5, 0, 0))

    def test_early_clock_out_calculates_undertime(self) -> None:
        late, undertime, overtime = calculate_attendance_metrics(
            expected_clock_in_at=datetime(2026, 10, 9, 1, tzinfo=timezone.utc),
            expected_clock_out_at=datetime(2026, 10, 9, 10, tzinfo=timezone.utc),
            actual_clock_in_at=datetime(2026, 10, 9, 1, tzinfo=timezone.utc),
            actual_clock_out_at=datetime(2026, 10, 9, 9, 20, tzinfo=timezone.utc),
        )

        self.assertEqual((late, undertime, overtime), (0, 40, 0))

    def test_overtime_is_potential_only_and_requires_eligibility_and_threshold(self) -> None:
        expected_in = datetime(2026, 10, 9, 1, tzinfo=timezone.utc)
        expected_out = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
        actual_in = datetime(2026, 10, 9, 0, 45, tzinfo=timezone.utc)
        actual_out = datetime(2026, 10, 9, 10, 45, tzinfo=timezone.utc)

        self.assertEqual(
            calculate_attendance_metrics(
                expected_clock_in_at=expected_in,
                expected_clock_out_at=expected_out,
                actual_clock_in_at=actual_in,
                actual_clock_out_at=actual_out,
                ot_eligible=True,
                minimum_ot_minutes=30,
                pre_shift_ot_allowed=True,
            )[2],
            60,
        )
        self.assertEqual(
            calculate_attendance_metrics(
                expected_clock_in_at=expected_in,
                expected_clock_out_at=expected_out,
                actual_clock_in_at=actual_in,
                actual_clock_out_at=actual_out,
                ot_eligible=True,
                minimum_ot_minutes=61,
                pre_shift_ot_allowed=True,
            )[2],
            0,
        )
        self.assertEqual(
            calculate_attendance_metrics(
                expected_clock_in_at=expected_in,
                expected_clock_out_at=expected_out,
                actual_clock_in_at=actual_in,
                actual_clock_out_at=actual_out,
                ot_eligible=False,
                pre_shift_ot_allowed=True,
            )[2],
            0,
        )

    def test_overnight_shift_uses_absolute_expected_times(self) -> None:
        late, undertime, overtime = calculate_attendance_metrics(
            expected_clock_in_at=datetime(2026, 10, 9, 22, tzinfo=timezone.utc),
            expected_clock_out_at=datetime(2026, 10, 10, 6, tzinfo=timezone.utc),
            actual_clock_in_at=datetime(2026, 10, 9, 22, tzinfo=timezone.utc),
            actual_clock_out_at=datetime(2026, 10, 10, 6, 30, tzinfo=timezone.utc),
            ot_eligible=True,
            minimum_ot_minutes=15,
        )

        self.assertEqual((late, undertime, overtime), (0, 0, 30))

    def test_overtime_threshold_is_applied_after_subtracting_breaks(self) -> None:
        expected_out = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
        actual_out = datetime(2026, 10, 9, 11, tzinfo=timezone.utc)
        break_intervals = ((
            datetime(2026, 10, 9, 10, 15, tzinfo=timezone.utc),
            datetime(2026, 10, 9, 10, 30, tzinfo=timezone.utc),
        ),)

        self.assertEqual(
            calculate_attendance_metrics(
                expected_clock_in_at=None,
                expected_clock_out_at=expected_out,
                actual_clock_in_at=None,
                actual_clock_out_at=actual_out,
                ot_eligible=True,
                minimum_ot_minutes=45,
                break_intervals=break_intervals,
            )[2],
            45,
        )
        self.assertEqual(
            calculate_attendance_metrics(
                expected_clock_in_at=None,
                expected_clock_out_at=expected_out,
                actual_clock_in_at=None,
                actual_clock_out_at=actual_out,
                ot_eligible=True,
                minimum_ot_minutes=46,
                break_intervals=break_intervals,
            )[2],
            0,
        )

    def test_overtime_crossing_midnight_splits_regular_and_night_overtime(self) -> None:
        ph_timezone = ZoneInfo("Asia/Manila")
        expected_in = datetime(2026, 10, 9, 9, tzinfo=ph_timezone)
        expected_out = datetime(2026, 10, 9, 18, tzinfo=ph_timezone)
        actual_in = expected_in
        actual_out = datetime(2026, 10, 10, 2, tzinfo=ph_timezone)
        break_intervals = ((
            datetime(2026, 10, 9, 23, tzinfo=ph_timezone),
            datetime(2026, 10, 10, 0, tzinfo=ph_timezone),
        ),)

        overtime = calculate_overtime_breakdown(
            expected_clock_in_at=expected_in,
            expected_clock_out_at=expected_out,
            actual_clock_in_at=actual_in,
            actual_clock_out_at=actual_out,
            ot_eligible=True,
            minimum_ot_minutes=7 * 60,
            break_intervals=break_intervals,
        )

        self.assertEqual(overtime, (4 * 60, 3 * 60, 7 * 60))

    def test_overtime_starting_after_midnight_counts_previous_night_window(self) -> None:
        ph_timezone = ZoneInfo("Asia/Manila")
        expected_out = datetime(2026, 10, 9, 2, tzinfo=ph_timezone)
        actual_out = datetime(2026, 10, 9, 9, tzinfo=ph_timezone)

        overtime = calculate_overtime_breakdown(
            expected_clock_in_at=datetime(2026, 10, 8, 17, tzinfo=ph_timezone),
            expected_clock_out_at=expected_out,
            actual_clock_in_at=datetime(2026, 10, 8, 17, tzinfo=ph_timezone),
            actual_clock_out_at=actual_out,
            ot_eligible=True,
        )

        self.assertEqual(overtime, (3 * 60, 4 * 60, 7 * 60))

    def test_overtime_minimum_applies_to_the_combined_overtime(self) -> None:
        ph_timezone = ZoneInfo("Asia/Manila")

        overtime = calculate_overtime_breakdown(
            expected_clock_in_at=datetime(2026, 10, 9, 9, tzinfo=ph_timezone),
            expected_clock_out_at=datetime(2026, 10, 9, 18, tzinfo=ph_timezone),
            actual_clock_in_at=datetime(2026, 10, 9, 9, tzinfo=ph_timezone),
            actual_clock_out_at=datetime(2026, 10, 10, 2, tzinfo=ph_timezone),
            ot_eligible=True,
            minimum_ot_minutes=8 * 60 + 1,
        )

        self.assertEqual(overtime, (0, 0, 0))

    def test_night_differential_counts_philippines_night_hours_less_breaks(self) -> None:
        ph_timezone = ZoneInfo("Asia/Manila")
        break_intervals = ((
            datetime(2026, 10, 9, 1, tzinfo=ph_timezone),
            datetime(2026, 10, 9, 2, tzinfo=ph_timezone),
        ),)

        minutes = calculate_night_differential_minutes(
            actual_clock_in_at=datetime(2026, 10, 8, 21, tzinfo=ph_timezone),
            actual_clock_out_at=datetime(2026, 10, 9, 7, tzinfo=ph_timezone),
            break_intervals=break_intervals,
        )

        self.assertEqual(minutes, 7 * 60)

    def test_only_meal_and_overtime_breaks_are_excluded(self) -> None:
        record = AttendanceEntity(
            user_id=UUID(int=1),
            work_date=date(2026, 10, 9),
            first_break_out_at=datetime(2026, 10, 9, 1, tzinfo=timezone.utc),
            first_break_in_at=datetime(2026, 10, 9, 1, 15, tzinfo=timezone.utc),
            meal_break_out_at=datetime(2026, 10, 9, 5, tzinfo=timezone.utc),
            meal_break_in_at=datetime(2026, 10, 9, 5, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(
            get_unpaid_break_intervals(record),
            (
                (record.meal_break_out_at, record.meal_break_in_at),
                (None, None),
            ),
        )


if __name__ == "__main__":
    unittest.main()
