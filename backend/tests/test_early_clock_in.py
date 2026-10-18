import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.attendance.application.use_case import (
    ClockAttendanceInputDTO,
    ClockAttendanceUseCase,
    ScheduleDayConfiguration,
    calculate_attendance_metrics,
    calculate_overtime_breakdown,
    validate_early_clock_in,
)
from app.attendance.domain.entities.attendance import AttendanceEntity
from app.auth.domain.entities.user import UserEntity
from app.enrollment.domain.entities.enrollment import FaceEnrollmentEntity
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity


class EarlyClockInValidationTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 12, 9, tzinfo=ZoneInfo("Asia/Manila"))

    def test_exact_early_boundary_is_allowed(self):
        validate_early_clock_in(self.start - timedelta(minutes=30), self.start, 30)

    def test_one_second_before_boundary_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "08:30 AM Philippine time"):
            validate_early_clock_in(self.start - timedelta(minutes=30, seconds=1), self.start, 30)

    def test_zero_blocks_early_but_allows_scheduled_and_late_punches(self):
        with self.assertRaisesRegex(ValueError, "too early"):
            validate_early_clock_in(self.start - timedelta(seconds=1), self.start, 0)
        validate_early_clock_in(self.start, self.start, 0)
        validate_early_clock_in(self.start + timedelta(minutes=10), self.start, 0)

    def test_timezones_compare_absolute_instants(self):
        validate_early_clock_in(
            (self.start - timedelta(minutes=30)).astimezone(timezone.utc), self.start, 30,
        )

    def test_midnight_start_allows_previous_day_punch(self):
        start = self.start.replace(hour=0)
        validate_early_clock_in(start - timedelta(minutes=15), start, 30)

    def test_negative_allowance_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            validate_early_clock_in(self.start, self.start, -1)

    def test_grace_and_overtime_remain_separate(self):
        end = self.start + timedelta(hours=9)
        late, undertime, _ = calculate_attendance_metrics(
            expected_clock_in_at=self.start, expected_clock_out_at=end,
            actual_clock_in_at=self.start + timedelta(minutes=10),
            actual_clock_out_at=end, grace_minutes=5,
        )
        self.assertEqual((late, undertime), (5, 0))
        self.assertEqual(calculate_overtime_breakdown(
            expected_clock_in_at=self.start, expected_clock_out_at=end,
            actual_clock_in_at=self.start - timedelta(minutes=30),
            actual_clock_out_at=end, ot_eligible=True, pre_shift_ot_allowed=False,
        ), (0, 0, 0))

    def test_manila_lateness_is_elapsed_time_after_grace(self):
        expected = datetime(2026, 10, 14, 16, 0, tzinfo=ZoneInfo("Asia/Manila"))
        actual = datetime(2026, 10, 14, 18, 24, 31, 486000, tzinfo=ZoneInfo("Asia/Manila"))

        late, _, _ = calculate_attendance_metrics(
            expected_clock_in_at=expected,
            expected_clock_out_at=None,
            actual_clock_in_at=actual,
            actual_clock_out_at=None,
            grace_minutes=15,
        )

        self.assertEqual(late, 129)


class ClockUow:
    def __init__(self, repos):
        self.repos = repos

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get_repo(self, entity, model):
        return self.repos[entity]


class EarlyClockInUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id, self.employee_id, self.template_id = uuid4(), uuid4(), uuid4()
        self.start = datetime(2026, 10, 12, 9, tzinfo=ZoneInfo("Asia/Manila"))
        self.now = self.start - timedelta(minutes=30)
        self.schedule = ScheduleDayConfiguration(
            work_type="REG", expected_clock_in_at=self.start,
            expected_clock_out_at=self.start + timedelta(hours=9),
            schedule_template_id=self.template_id, early_clock_in_allowance_minutes=30,
            schedule_context={"early_clock_in_allowance_minutes": 30},
        )
        self.attendance = SimpleNamespace(
            find_all=AsyncMock(return_value=[]),
            add=AsyncMock(side_effect=lambda record: record),
        )
        repos = {
            AttendanceEntity: self.attendance,
            UserEntity: SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
                employee_id=self.employee_id, is_active=True, account_status="ACTIVE",
            ))),
            EmployeeEntity: SimpleNamespace(find_one=AsyncMock(return_value=EmployeeEntity(
                employee_no="E1", first_name="Test", last_name="Employee", id=self.employee_id,
            ))),
            FaceEnrollmentEntity: SimpleNamespace(find_all=AsyncMock(return_value=[
                SimpleNamespace(employee_id=self.employee_id, face_encoding=b"encoding"),
            ])),
        }
        face = SimpleNamespace(
            extract_face_encoding=Mock(return_value=b"encoding"),
            find_best_match=Mock(return_value=(self.employee_id, 0)),
        )
        self.use_case = ClockAttendanceUseCase(ClockUow(repos), face)
        self.use_case._resolve_schedule_day = AsyncMock(return_value=self.schedule)
        self.use_case._resolve_day_type = AsyncMock(return_value="REG")

    async def clock_in(self):
        with patch("app.attendance.application.use_case.datetime", wraps=datetime) as clock:
            clock.now.return_value = self.now.astimezone(timezone.utc)
            return await self.use_case._execute(ClockAttendanceInputDTO(
                user_id=self.user_id, image_bytes=b"image", enforce_geofence=False,
            ))

    async def test_rejected_punch_does_not_create_attendance(self):
        self.now -= timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError, "too early"):
            await self.clock_in()
        self.attendance.add.assert_not_awaited()

    async def test_boundary_punch_preserves_schedule_and_snapshots_allowance(self):
        await self.clock_in()
        record = self.attendance.add.call_args.args[0]
        self.assertEqual(record.expected_clock_in_at, self.start)
        self.assertEqual(record.expected_clock_out_at, self.start + timedelta(hours=9))
        self.assertEqual(record.punch_metadata["schedule_context"]["early_clock_in_allowance_minutes"], 30)
        self.assertEqual(record.late_minutes, 0)

    async def test_previous_evening_punch_uses_next_days_shift(self):
        self.now = self.start.replace(hour=23, minute=45)
        next_start = self.start.replace(hour=0) + timedelta(days=1)
        next_schedule = ScheduleDayConfiguration(
            work_type="REG", expected_clock_in_at=next_start,
            expected_clock_out_at=next_start + timedelta(hours=8),
            schedule_template_id=self.template_id, early_clock_in_allowance_minutes=30,
            schedule_context={"early_clock_in_allowance_minutes": 30},
        )
        self.use_case._resolve_schedule_day.side_effect = [self.schedule, next_schedule]
        await self.clock_in()
        record = self.attendance.add.call_args.args[0]
        self.assertEqual(record.work_date, date(2026, 10, 13))
        self.assertEqual(record.expected_clock_in_at, next_start)

    async def test_open_attendance_at_24_hours_does_not_block_new_clock_in(self):
        stale_attendance = AttendanceEntity(
            user_id=self.user_id,
            work_date=self.start.date() - timedelta(days=1),
            clock_in_at=self.now - timedelta(hours=24),
        )
        self.attendance.find_all.return_value = [stale_attendance]

        await self.clock_in()

        self.attendance.add.assert_awaited_once()
        new_attendance = self.attendance.add.call_args.args[0]
        self.assertEqual(new_attendance.work_date, self.start.date())
        self.assertIsNone(stale_attendance.clock_out_at)

    async def test_unassigned_employee_keeps_existing_behavior(self):
        self.now -= timedelta(hours=2)
        self.use_case._resolve_schedule_day.return_value = ScheduleDayConfiguration(
            work_type="REG", expected_clock_in_at=self.start,
            expected_clock_out_at=self.start + timedelta(hours=9),
        )
        await self.clock_in()
        self.attendance.add.assert_awaited_once()
