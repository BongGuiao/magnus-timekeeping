import unittest
from datetime import date, datetime, time
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.attendance.infrastructure.attendance_merge_router import (
    BREAK_FIELDS,
    CreateAttendanceMergeRequest,
    _apply_schedule_calculations,
    _break_values,
    _merged_punches,
    _require_hr_admin,
)


MANILA = ZoneInfo("Asia/Manila")


def source(
    *,
    clock_in_at: datetime | None = None,
    clock_out_at: datetime | None = None,
    corrected_clock_in_at: datetime | None = None,
    corrected_clock_out_at: datetime | None = None,
    meal_break_out_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        clock_in_at=clock_in_at,
        clock_out_at=clock_out_at,
        corrected_clock_in_at=corrected_clock_in_at,
        corrected_clock_out_at=corrected_clock_out_at,
        first_break_out_at=None,
        first_break_in_at=None,
        meal_break_out_at=meal_break_out_at,
        meal_break_in_at=None,
        second_break_out_at=None,
        second_break_in_at=None,
        ot_break_out_at=None,
        ot_break_in_at=None,
    )


class AttendanceMergeTests(unittest.TestCase):
    def test_merge_uses_earliest_effective_in_and_latest_effective_out(self) -> None:
        first = source(
            clock_in_at=datetime(2026, 11, 2, 8, 10, tzinfo=MANILA),
        )
        second = source(
            corrected_clock_in_at=datetime(2026, 11, 2, 8, 58, tzinfo=MANILA),
            clock_out_at=datetime(2026, 11, 2, 17, 45, tzinfo=MANILA),
        )
        third = source(
            corrected_clock_out_at=datetime(2026, 11, 2, 18, 5, tzinfo=MANILA),
        )

        actual_in, actual_out = _merged_punches([first, second, third])

        self.assertEqual(actual_in, first.clock_in_at)
        self.assertEqual(actual_out, third.corrected_clock_out_at)

    def test_merge_rejects_missing_aggregate_punches(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            _merged_punches([source(clock_in_at=datetime(2026, 11, 2, 8, 0, tzinfo=MANILA))])

        self.assertEqual(raised.exception.status_code, 409)

    def test_merge_rejects_latest_sequence_without_clock_out(self) -> None:
        first = source(
            clock_in_at=datetime(2026, 11, 2, 8, 0, tzinfo=MANILA),
            clock_out_at=datetime(2026, 11, 2, 16, 0, tzinfo=MANILA),
        )
        last = source(
            clock_in_at=datetime(2026, 11, 2, 16, 30, tzinfo=MANILA),
        )

        with self.assertRaises(HTTPException) as raised:
            _merged_punches([first, last])

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("latest source sequence", raised.exception.detail)

    def test_merge_uses_hr_verified_clock_out_when_latest_sequence_is_missing_one(self) -> None:
        first = source(
            clock_in_at=datetime(2020, 11, 2, 8, 0, tzinfo=MANILA),
            clock_out_at=datetime(2020, 11, 2, 16, 0, tzinfo=MANILA),
        )
        last = source(
            clock_in_at=datetime(2020, 11, 2, 16, 30, tzinfo=MANILA),
        )
        verified_clock_out = datetime(2020, 11, 2, 18, 0, tzinfo=MANILA)

        actual_in, actual_out = _merged_punches(
            [first, last],
            verified_clock_out_at=verified_clock_out,
        )

        self.assertEqual(actual_in, first.clock_in_at)
        self.assertEqual(actual_out, verified_clock_out)
        self.assertIsNone(last.clock_out_at)

    def test_merge_rejects_verified_clock_out_before_latest_sequence(self) -> None:
        latest_in = datetime(2020, 11, 2, 16, 30, tzinfo=MANILA)
        with self.assertRaises(HTTPException) as raised:
            _merged_punches(
                [
                    source(
                        clock_in_at=datetime(2020, 11, 2, 8, 0, tzinfo=MANILA),
                        clock_out_at=datetime(2020, 11, 2, 16, 0, tzinfo=MANILA),
                    ),
                    source(clock_in_at=latest_in),
                ],
                verified_clock_out_at=datetime(2020, 11, 2, 16, 0, tzinfo=MANILA),
            )

        self.assertEqual(raised.exception.status_code, 422)

    def test_merge_request_requires_timezone_on_verified_clock_out(self) -> None:
        with self.assertRaisesRegex(ValueError, "must include a timezone"):
            CreateAttendanceMergeRequest(
                source_attendance_ids=[uuid4(), uuid4()],
                schedule_template_id=uuid4(),
                reason="Verified punch records",
                verified_clock_out_at=datetime(2020, 11, 2, 18, 0),
            )

    def test_merge_rejects_conflicting_break_punches(self) -> None:
        first = source(meal_break_out_at=datetime(2026, 11, 2, 12, 0, tzinfo=MANILA))
        second = source(meal_break_out_at=datetime(2026, 11, 2, 12, 5, tzinfo=MANILA))

        with self.assertRaises(HTTPException) as raised:
            _break_values([first, second])

        self.assertEqual(raised.exception.status_code, 409)

    def test_canonical_attendance_uses_selected_schedule_for_calculations(self) -> None:
        work_date = date(2026, 11, 2)
        canonical = SimpleNamespace(
            corrected_clock_in_at=datetime(2026, 11, 2, 8, 10, tzinfo=MANILA),
            corrected_clock_out_at=datetime(2026, 11, 2, 18, 0, tzinfo=MANILA),
            punch_metadata={},
            **dict.fromkeys(BREAK_FIELDS),
        )
        template = SimpleNamespace(
            id=uuid4(),
            grace_minutes=0,
            ot_eligible=True,
            minimum_ot_minutes=0,
            pre_shift_ot_allowed=True,
        )
        segments = [
            SimpleNamespace(
                id=uuid4(),
                segment_type="WORK",
                start_time=time(9, 0),
                end_time=time(17, 0),
                end_day_offset=0,
                flex_start_minutes=0,
                break_slot=None,
            )
        ]

        _apply_schedule_calculations(canonical, template, segments, work_date)

        self.assertEqual(canonical.expected_clock_in_at, datetime(2026, 11, 2, 9, 0, tzinfo=MANILA))
        self.assertEqual(canonical.expected_clock_out_at, datetime(2026, 11, 2, 17, 0, tzinfo=MANILA))
        self.assertEqual(canonical.regular_overtime_minutes, 110)
        self.assertEqual(canonical.late_minutes, 0)
        self.assertEqual(canonical.undertime_minutes, 0)
        self.assertEqual(canonical.approved_hours_worked, 9 + 50 / 60)

    def test_only_hr_admin_can_merge_or_view_audit(self) -> None:
        user_id = uuid4()

        self.assertEqual(
            _require_hr_admin({"sub": str(user_id), "role_codes": ["HR_ADMIN"]}),
            user_id,
        )
        with self.assertRaises(HTTPException) as raised:
            _require_hr_admin({"sub": str(user_id), "role_codes": ["SYSTEM_ADMIN"]})

        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
