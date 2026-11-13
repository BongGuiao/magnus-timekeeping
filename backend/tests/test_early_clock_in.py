import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.attendance.application.use_case import (
    ClockAttendanceInputDTO,
    ClockAttendanceUseCase,
    GetLastAttendanceInputDTO,
    GetLastAttendanceUseCase,
    ScheduleDayConfiguration,
    attendance_allows_clock_out,
    calculate_attendance_metrics,
    calculate_overtime_breakdown,
    validate_early_clock_in,
)
from app.attendance.domain.entities.attendance import AttendanceEntity
from app.auth.domain.entities.user import UserEntity
from app.auth.infrastructure.approval_routing import ApprovalRoutingError
from app.enrollment.domain.entities.enrollment import FaceEnrollmentEntity
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity


class AttendanceActionResolutionTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 13)

    def attendance(self, work_date, clock_in_at, expected_in=None, expected_out=None):
        return AttendanceEntity(
            user_id=uuid4(),
            work_date=work_date,
            clock_in_at=clock_in_at,
            expected_clock_in_at=expected_in,
            expected_clock_out_at=expected_out,
        )

    def test_open_attendance_from_today_allows_clock_out(self):
        now = datetime(2026, 10, 13, 10, tzinfo=ZoneInfo("Asia/Manila"))
        record = self.attendance(
            self.today, now - timedelta(hours=1),
            now - timedelta(hours=1), now + timedelta(hours=8),
        )
        self.assertTrue(attendance_allows_clock_out(record, now))

    def test_previous_work_date_is_active_for_an_overnight_shift(self):
        now = datetime(2026, 10, 13, 2, tzinfo=ZoneInfo("Asia/Manila"))
        expected_in = datetime(2026, 10, 12, 22, tzinfo=ZoneInfo("Asia/Manila"))
        expected_out = datetime(2026, 10, 13, 6, tzinfo=ZoneInfo("Asia/Manila"))
        record = self.attendance(
            self.today - timedelta(days=1), expected_in, expected_in, expected_out,
        )
        self.assertTrue(attendance_allows_clock_out(record, now))

    def test_previous_date_day_shift_does_not_block_a_new_clock_in(self):
        expected_in = datetime(2026, 10, 12, 9, tzinfo=ZoneInfo("Asia/Manila"))
        record = self.attendance(
            self.today - timedelta(days=1),
            expected_in,
            expected_in,
            expected_in + timedelta(hours=9),
        )
        now = datetime(2026, 10, 13, 8, tzinfo=ZoneInfo("Asia/Manila"))
        self.assertFalse(attendance_allows_clock_out(record, now))

    def test_open_attendance_at_24_hours_is_stale(self):
        expected_in = datetime(2026, 10, 12, 22, tzinfo=ZoneInfo("Asia/Manila"))
        record = self.attendance(
            self.today - timedelta(days=1),
            expected_in,
            expected_in,
            datetime(2026, 10, 13, 6, tzinfo=ZoneInfo("Asia/Manila")),
        )
        now = expected_in + timedelta(hours=24)
        self.assertFalse(attendance_allows_clock_out(record, now))

    def test_early_punch_for_tomorrow_is_still_an_open_shift(self):
        now = datetime(2026, 10, 12, 23, 45, tzinfo=ZoneInfo("Asia/Manila"))
        expected_in = datetime(2026, 10, 13, 0, tzinfo=ZoneInfo("Asia/Manila"))
        record = self.attendance(
            expected_in.date(), now, expected_in, expected_in + timedelta(hours=8),
        )
        self.assertTrue(attendance_allows_clock_out(record, now))


class KioskAttendanceStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 13, 2, tzinfo=ZoneInfo("Asia/Manila"))

    def attendance(self, work_date, clock_in, expected_in=None, expected_out=None):
        return AttendanceEntity(
            user_id=uuid4(),
            work_date=work_date,
            clock_in_at=clock_in,
            expected_clock_in_at=expected_in,
            expected_clock_out_at=expected_out,
        )

    async def resolve(self, records, open_records, for_kiosk=True):
        repo = SimpleNamespace(find_all=AsyncMock(side_effect=[records, open_records]))

        class FakeUow:
            session = SimpleNamespace()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def get_repo(self, entity, model):
                return repo

        use_case = GetLastAttendanceUseCase(FakeUow())
        with patch(
            "app.attendance.application.use_case.resolve_record_break_rules",
            new=AsyncMock(return_value=[]),
        ), patch("app.attendance.application.use_case.datetime", wraps=datetime) as clock:
            clock.now.return_value = self.now.astimezone(timezone.utc)
            result = await use_case.execute(GetLastAttendanceInputDTO(
                user_id=uuid4(), for_kiosk=for_kiosk,
            ))
        return result, repo

    async def test_same_day_open_record_resolves_to_clock_out(self):
        record = self.attendance(
            self.now.date(), self.now - timedelta(hours=1),
        )
        result, _ = await self.resolve([record], [record])
        self.assertEqual(result.next_action, "clock_out")

    async def test_qualifying_overnight_record_resolves_to_clock_out(self):
        expected_in = self.now.replace(day=12, hour=22)
        expected_out = self.now.replace(hour=6)
        record = self.attendance(
            self.now.date() - timedelta(days=1), expected_in, expected_in, expected_out,
        )
        result, _ = await self.resolve([record], [record])
        self.assertEqual(result.next_action, "clock_out")

    async def test_prior_day_non_overnight_open_record_resolves_to_clock_in(self):
        expected_in = self.now.replace(day=12, hour=9)
        record = self.attendance(
            self.now.date() - timedelta(days=1),
            expected_in,
            expected_in,
            expected_in + timedelta(hours=9),
        )
        result, _ = await self.resolve([record], [record])
        self.assertEqual(result.next_action, "clock_in")

    async def test_24_hour_open_record_resolves_to_clock_in(self):
        clock_in = self.now - timedelta(hours=24)
        record = self.attendance(
            self.now.date() - timedelta(days=1),
            clock_in,
            clock_in,
            clock_in + timedelta(hours=8),
        )
        result, _ = await self.resolve([record], [record])
        self.assertEqual(result.next_action, "clock_in")

    async def test_non_kiosk_last_attendance_does_not_resolve_or_change_mobile_state(self):
        record = self.attendance(self.now.date(), self.now - timedelta(hours=1))
        result, repo = await self.resolve([record], [], for_kiosk=False)
        self.assertIsNone(result.next_action)
        repo.find_all.assert_awaited_once()


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
        self.session = SimpleNamespace(
            scalar=AsyncMock(side_effect=lambda statement: repos[UserEntity].get.return_value),
        )

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

    async def clock_in(self, device_approved=True, requested_action=None, kiosk_action=False):
        with patch("app.attendance.application.use_case.datetime", wraps=datetime) as clock:
            clock.now.return_value = self.now.astimezone(timezone.utc)
            return await self.use_case._execute(ClockAttendanceInputDTO(
                user_id=self.user_id, image_bytes=b"image", enforce_geofence=False,
                device_approved=device_approved, requested_action=requested_action,
                kiosk_action=kiosk_action,
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

    async def test_flagged_clock_in_is_recorded_when_org_approver_is_missing(self):
        attendance_id = uuid4()

        def persist(record):
            record.id = attendance_id
            return record

        self.attendance.add.side_effect = persist
        with patch(
            "app.attendance.application.use_case.assign_org_approval",
            new=AsyncMock(side_effect=ApprovalRoutingError("No manager configured.")),
        ), patch(
            "app.attendance.application.use_case.save_approval_route", new=AsyncMock()
        ) as save, self.assertLogs("app.attendance.application.use_case", level="WARNING"):
            result = await self.clock_in(device_approved=False)

        self.assertTrue(result.approval_required)
        self.assertEqual(self.attendance.add.await_args.args[0].record_status, "INVALID")
        self.assertEqual(save.await_args.kwargs["resource_id"], attendance_id)
        self.assertEqual(save.await_args.kwargs["routing_error"], "No manager configured.")

    async def test_flagged_clock_out_assigns_route_when_record_was_valid(self):
        self.now = self.start + timedelta(hours=9)
        record = AttendanceEntity(
            id=uuid4(), user_id=self.user_id, work_date=self.start.date(),
            clock_in_at=self.start, expected_clock_in_at=self.start,
            expected_clock_out_at=self.now, record_status="VALID",
            punch_metadata={"schedule_context": {"ot_eligible": False}},
        )
        self.attendance.find_all.return_value = [record]
        self.attendance.update = AsyncMock(side_effect=lambda updated: updated)
        with patch(
            "app.attendance.application.use_case.resolve_record_break_rules",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.attendance.application.use_case.assign_invalid_attendance_approver", new=AsyncMock()
        ) as assign:
            result = await self.clock_in(device_approved=False)
        self.assertTrue(result.approval_required)
        self.assertEqual(record.record_status, "INVALID")
        self.assertEqual(assign.await_args.args[1:], (
            record.id, self.employee_id, self.user_id, self.now.date(),
        ))

    async def test_clock_out_preserves_existing_invalid_route(self):
        self.now = self.start + timedelta(hours=9)
        record = AttendanceEntity(
            id=uuid4(), user_id=self.user_id, work_date=self.start.date(),
            clock_in_at=self.start, expected_clock_in_at=self.start,
            expected_clock_out_at=self.now, record_status="INVALID",
            punch_metadata={"schedule_context": {"ot_eligible": False}},
        )
        self.attendance.find_all.return_value = [record]
        self.attendance.update = AsyncMock(side_effect=lambda updated: updated)
        with patch(
            "app.attendance.application.use_case.resolve_record_break_rules",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.attendance.application.use_case.assign_invalid_attendance_approver", new=AsyncMock()
        ) as assign:
            result = await self.clock_in(device_approved=False)
        self.assertTrue(result.approval_required)
        assign.assert_not_awaited()

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
        self.attendance.find_all.side_effect = [[stale_attendance], []]

        await self.clock_in()

        self.attendance.add.assert_awaited_once()
        new_attendance = self.attendance.add.call_args.args[0]
        self.assertEqual(new_attendance.work_date, self.start.date())
        self.assertIsNone(stale_attendance.clock_out_at)

    async def test_previous_date_day_shift_does_not_block_a_new_clock_in(self):
        previous_day = self.start - timedelta(days=1)
        stale_attendance = AttendanceEntity(
            user_id=self.user_id,
            work_date=previous_day.date(),
            expected_clock_in_at=previous_day,
            expected_clock_out_at=previous_day + timedelta(hours=9),
            clock_in_at=previous_day,
        )
        self.attendance.find_all.side_effect = [[stale_attendance], []]

        await self.clock_in(requested_action="clock_in", kiosk_action=True)

        self.attendance.add.assert_awaited_once()
        self.assertIsNone(stale_attendance.clock_out_at)

    async def test_mobile_keeps_a_recent_open_previous_day_record_as_clock_out(self):
        previous_day = self.start - timedelta(days=1)
        open_attendance = AttendanceEntity(
            user_id=self.user_id,
            work_date=previous_day.date(),
            expected_clock_in_at=previous_day,
            expected_clock_out_at=previous_day + timedelta(hours=9),
            clock_in_at=previous_day,
        )
        self.attendance.find_all.return_value = [open_attendance]
        self.attendance.update = AsyncMock(side_effect=lambda record: record)
        with patch(
            "app.attendance.application.use_case.resolve_record_break_rules",
            new=AsyncMock(return_value=[]),
        ):
            result = await self.clock_in()

        self.assertEqual(result.action, "clock_out")
        self.assertEqual(open_attendance.clock_out_at, self.now.astimezone(timezone.utc))

    async def test_unassigned_employee_keeps_existing_behavior(self):
        self.now -= timedelta(hours=2)
        self.use_case._resolve_schedule_day.return_value = ScheduleDayConfiguration(
            work_type="REG", expected_clock_in_at=self.start,
            expected_clock_out_at=self.start + timedelta(hours=9),
        )
        await self.clock_in()
        self.attendance.add.assert_awaited_once()
