import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.attendance.application import return_to_work_screening as screening
from app.attendance.domain.return_to_work_screening import ReviewDayStatus
from app.attendance.infrastructure.db_model import AttendanceModel


class ReturnToWorkScreeningServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id = uuid4()
        self.employee_id = uuid4()
        self.today = date(2026, 11, 27)
        self.now = datetime(2026, 11, 27, 10, tzinfo=timezone.utc)
        self.schedule = SimpleNamespace(
            work_type="REG", schedule_context={"assignment": "test"},
            schedule_template_id=uuid4(), attendance_mode="PUNCH_REQUIRED",
            expected_clock_out_at=self.now - timedelta(hours=1),
        )
        self.session = SimpleNamespace(scalars=AsyncMock())
        self.records = []
        self.session.scalars.return_value = SimpleNamespace(all=lambda: self.records)
        self.schedule_patch = patch.object(
            screening, "resolve_schedule_day", new=AsyncMock(return_value=self.schedule),
        )
        self.day_type_patch = patch.object(
            screening, "resolve_attendance_day_type", new=AsyncMock(return_value="REG"),
        )
        self.exception_patch = patch.object(
            screening, "_has_approved_exception", new=AsyncMock(return_value=False),
        )
        for item in (self.schedule_patch, self.day_type_patch, self.exception_patch):
            item.start()
            self.addCleanup(item.stop)

    def absence(self, work_date):
        return AttendanceModel(
            user_id=self.user_id, work_date=work_date, is_absent=True,
            record_status="VALID",
        )

    async def streak(self):
        return await screening.load_current_absence_streak(
            self.session, self.user_id, self.employee_id,
            self.today - timedelta(days=5), self.today, self.now,
        )

    async def test_three_completed_absences_are_detected(self):
        self.records = [self.absence(self.today - timedelta(days=n)) for n in range(3)]
        self.assertEqual(await self.streak(), (
            self.today - timedelta(days=2), self.today - timedelta(days=1), self.today,
        ))

    async def test_incomplete_third_shift_does_not_count(self):
        self.records = [self.absence(self.today - timedelta(days=n)) for n in range(3)]

        async def schedule_for_day(_session, _employee_id, work_date):
            return SimpleNamespace(
                **{**vars(self.schedule), "expected_clock_out_at": (
                    self.now + timedelta(hours=1) if work_date == self.today
                    else self.now - timedelta(days=1)
                )},
            )

        screening.resolve_schedule_day.side_effect = schedule_for_day
        self.assertEqual(await self.streak(), (
            self.today - timedelta(days=2), self.today - timedelta(days=1),
        ))

    async def test_approved_exception_breaks_streak(self):
        self.records = [self.absence(self.today - timedelta(days=n)) for n in range(3)]
        screening._has_approved_exception.side_effect = [False, True]
        self.assertEqual(await self.streak(), (self.today,))

    async def test_duplicate_records_are_unknown(self):
        status = await screening.review_day_status(
            self.session, self.employee_id, self.today,
            [self.absence(self.today), self.absence(self.today)], self.now,
        )
        self.assertEqual(status, ReviewDayStatus.UNKNOWN)

    async def test_missing_schedule_does_not_infer_absence(self):
        self.schedule.schedule_context = None
        status = await screening.review_day_status(
            self.session, self.employee_id, self.today, [self.absence(self.today)], self.now,
        )
        self.assertEqual(status, ReviewDayStatus.UNKNOWN)

    async def test_rest_day_and_holiday_are_skipped(self):
        self.schedule.work_type = "REST"
        self.assertEqual(await screening.review_day_status(
            self.session, self.employee_id, self.today, [], self.now,
        ), ReviewDayStatus.REST_DAY)
        self.schedule.work_type = "REG"
        screening.resolve_attendance_day_type.return_value = "RH"
        self.assertEqual(await screening.review_day_status(
            self.session, self.employee_id, self.today, [], self.now,
        ), ReviewDayStatus.HOLIDAY)

    async def test_present_record_breaks_streak_even_with_an_absence_record(self):
        present = AttendanceModel(
            user_id=self.user_id, work_date=self.today, record_status="VALID",
            corrected_clock_in_at=self.now - timedelta(hours=5), is_absent=False,
        )
        self.assertEqual(await screening.review_day_status(
            self.session, self.employee_id, self.today, [self.absence(self.today), present], self.now,
        ), ReviewDayStatus.PRESENT)

    async def test_today_presence_interrupts_even_before_shift_end(self):
        self.schedule.expected_clock_out_at = self.now + timedelta(hours=4)
        present = AttendanceModel(
            user_id=self.user_id, work_date=self.today, record_status="VALID",
            clock_in_at=self.now - timedelta(hours=1), is_absent=False,
        )
        self.assertEqual(await screening.review_day_status(
            self.session, self.employee_id, self.today, [present], self.now,
        ), ReviewDayStatus.PRESENT)


if __name__ == "__main__":
    unittest.main()
