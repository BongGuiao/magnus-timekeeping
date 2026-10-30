import unittest
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.attendance.application.use_case import (
    RecordBreakInputDTO,
    RecordBreakUseCase,
    calculate_attendance_metrics,
    calculate_break_policy,
    calculate_net_nonpayable_break_minutes,
)
from app.attendance.domain.entities.attendance import AttendanceEntity
from app.auth.domain.entities.user import UserEntity
from app.enrollment.domain.entities.enrollment import FaceEnrollmentEntity
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity
from app.filemaintenance.schedule.application.use_case import (
    ScheduleSegmentReferenceError,
    _normalize_break_segment,
)
from app.filemaintenance.schedule.domain.entities.schedule_segment import ScheduleSegmentEntity


def rule(slot, minutes, segment_type="PAID_BREAK", auto_deduct=False):
    return {
        "break_slot": slot,
        "break_minutes": minutes,
        "segment_type": segment_type,
        "auto_deduct": auto_deduct,
    }


class FlexibleBreakCalculationTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
        self.record = AttendanceEntity(user_id=uuid4(), work_date=date(2026, 10, 12))

    def punch(self, name, duration):
        setattr(self.record, f"{name}_out_at", self.start)
        setattr(self.record, f"{name}_in_at", self.start + timedelta(minutes=duration))

    def test_paid_allowance_has_no_undertime_at_boundary(self):
        self.punch("first_break", 15)
        excess, unpaid, intervals = calculate_break_policy(self.record, [rule("FIRST_BREAK", 15)])
        self.assertEqual((excess, unpaid), (0, 0))
        self.assertNotIn((self.start, self.start + timedelta(minutes=15)), intervals)

    def test_paid_excess_only_is_excluded_from_paid_time(self):
        self.punch("first_break", 21)
        excess, unpaid, intervals = calculate_break_policy(self.record, [rule("FIRST_BREAK", 15)])
        self.assertEqual((excess, unpaid), (6, 0))
        self.assertIn((self.start + timedelta(minutes=15), self.start + timedelta(minutes=21)), intervals)

    def test_each_paid_break_has_separate_allowance(self):
        self.punch("first_break", 10)
        self.punch("second_break", 25)
        excess, _, _ = calculate_break_policy(
            self.record, [rule("FIRST_BREAK", 15), rule("SECOND_BREAK", 15)],
        )
        self.assertEqual(excess, 10)

    def test_overtime_break_is_paid_up_to_its_schedule_allowance(self):
        self.punch("ot_break", 20)
        excess, unpaid, intervals = calculate_break_policy(
            self.record, [rule("OT_BREAK", 15)],
        )
        self.assertEqual((excess, unpaid), (5, 0))
        self.assertEqual(
            intervals,
            ((self.start + timedelta(minutes=15), self.start + timedelta(minutes=20)),),
        )

    def test_overtime_break_requires_a_schedule_allowance(self):
        self.punch("ot_break", 20)
        with self.assertRaisesRegex(ValueError, "paid OT_BREAK allowance"):
            calculate_break_policy(self.record, [])

    def test_unpaid_duration_is_deducted_once_and_excess_is_undertime(self):
        self.punch("meal_break", 75)
        excess, unpaid, intervals = calculate_break_policy(
            self.record, [rule("MEAL_BREAK", 60, "UNPAID_BREAK")],
        )
        self.assertEqual((excess, unpaid), (15, 75))
        self.assertEqual(intervals.count((self.start, self.start + timedelta(minutes=75))), 1)

    def test_missing_unpaid_punches_with_auto_deduct_uses_required_minutes(self):
        excess, unpaid, _ = calculate_break_policy(
            self.record, [rule("MEAL_BREAK", 60, "UNPAID_BREAK", True)],
        )
        self.assertEqual((excess, unpaid), (0, 60))

    def test_missing_unpaid_punches_without_auto_deduct_blocks_clockout(self):
        with self.assertRaisesRegex(ValueError, "required meal break"):
            calculate_break_policy(self.record, [rule("MEAL_BREAK", 60, "UNPAID_BREAK")])

    def test_missing_first_break_punches_without_auto_deduct_do_not_block_clockout(self):
        excess, unpaid, _ = calculate_break_policy(
            self.record, [rule("FIRST_BREAK", 15, "UNPAID_BREAK")],
        )
        self.assertEqual((excess, unpaid), (0, 0))

    def test_actual_punches_override_auto_deduct_not_added_to_it(self):
        self.punch("meal_break", 70)
        excess, unpaid, _ = calculate_break_policy(
            self.record, [rule("MEAL_BREAK", 60, "UNPAID_BREAK", True)],
        )
        self.assertEqual((excess, unpaid), (10, 70))

    def test_short_punched_meal_deducts_full_configured_allowance(self):
        self.punch("meal_break", 30)
        meal_rule = rule("MEAL_BREAK", 60, "UNPAID_BREAK")
        _, unpaid, intervals = calculate_break_policy(self.record, [meal_rule])
        self.assertEqual(unpaid, 60)
        self.assertEqual(
            calculate_net_nonpayable_break_minutes(
                self.record,
                [meal_rule],
                intervals,
                self.start - timedelta(hours=1),
                self.start + timedelta(hours=2),
            ),
            60,
        )

    def test_unused_paid_break_has_no_undertime(self):
        excess, unpaid, _ = calculate_break_policy(self.record, [rule("FIRST_BREAK", 15)])
        self.assertEqual((excess, unpaid), (0, 0))

    def test_overnight_break_duration(self):
        self.start = datetime(2026, 10, 12, 23, 50, tzinfo=timezone.utc)
        self.punch("first_break", 25)
        excess, _, _ = calculate_break_policy(self.record, [rule("FIRST_BREAK", 15)])
        self.assertEqual(excess, 10)

    def test_invalid_or_incomplete_break_rejected(self):
        self.record.first_break_out_at = self.start
        with self.assertRaisesRegex(ValueError, "completed interval"):
            calculate_break_policy(self.record, [rule("FIRST_BREAK", 15)])

    def test_legacy_unpaid_breaks_remain_excluded(self):
        self.punch("meal_break", 60)
        _, _, intervals = calculate_break_policy(self.record, [])
        self.assertIn((self.start, self.start + timedelta(minutes=60)), intervals)

    def test_break_excess_is_added_to_early_departure(self):
        self.punch("first_break", 20)
        excess, _, _ = calculate_break_policy(self.record, [rule("FIRST_BREAK", 15)])
        _, early_out, _ = calculate_attendance_metrics(
            expected_clock_in_at=self.start,
            expected_clock_out_at=self.start + timedelta(hours=9),
            actual_clock_in_at=self.start,
            actual_clock_out_at=self.start + timedelta(hours=9, minutes=-10),
        )
        self.assertEqual(early_out + excess, 15)


class SegmentRepo:
    def __init__(self, work):
        self.work = work
        self.calls = 0

    async def find_one(self, *conditions):
        self.calls += 1
        return self.work if self.calls == 1 else None


class FlexibleBreakSegmentValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_break_inherits_exact_work_window(self):
        template_id = uuid4()
        work = ScheduleSegmentEntity(
            schedule_template_id=template_id, segment_sequence=1, segment_type="WORK",
            start_time=time(22), end_time=time(6), end_day_offset=1,
        )
        payload = {
            "segment_type": "PAID_BREAK", "break_slot": "FIRST_BREAK",
            "work_segment_sequence": 1, "break_minutes": 15, "auto_deduct": False,
        }
        result = await _normalize_break_segment(SegmentRepo(work), template_id, payload)
        self.assertEqual((result["start_time"], result["end_time"], result["end_day_offset"]), (time(22), time(6), 1))
        self.assertTrue(result["punch_required"])

    async def test_overtime_break_must_be_configured_as_paid(self):
        template_id = uuid4()
        work = ScheduleSegmentEntity(
            schedule_template_id=template_id, segment_sequence=1, segment_type="WORK",
            start_time=time(17), end_time=time(21),
        )
        result = await _normalize_break_segment(
            SegmentRepo(work),
            template_id,
            {
                "segment_type": "PAID_BREAK",
                "break_slot": "OT_BREAK",
                "work_segment_sequence": 1,
                "break_minutes": 15,
                "auto_deduct": False,
            },
        )
        self.assertEqual(result["break_slot"], "OT_BREAK")
        self.assertEqual(result["segment_type"], "PAID_BREAK")

        with self.assertRaisesRegex(ScheduleSegmentReferenceError, "OT_BREAK must be configured as a paid break"):
            await _normalize_break_segment(
                SegmentRepo(work),
                template_id,
                {
                    "segment_type": "UNPAID_BREAK",
                    "break_slot": "OT_BREAK",
                    "work_segment_sequence": 1,
                    "break_minutes": 15,
                    "auto_deduct": False,
                },
            )

    async def test_break_allowance_cannot_exceed_work_window(self):
        template_id = uuid4()
        work = ScheduleSegmentEntity(
            schedule_template_id=template_id, segment_sequence=1, segment_type="WORK",
            start_time=time(9), end_time=time(10),
        )
        with self.assertRaisesRegex(ScheduleSegmentReferenceError, "within the WORK duration"):
            await _normalize_break_segment(SegmentRepo(work), template_id, {
                "segment_type": "PAID_BREAK", "break_slot": "FIRST_BREAK",
                "work_segment_sequence": 1, "break_minutes": 61,
            })


class BreakUow:
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


class FlexibleBreakPunchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id = uuid4()
        self.employee_id = uuid4()
        self.now = datetime(2026, 10, 12, 5, tzinfo=timezone.utc)
        self.rules = [{
            **rule("SECOND_BREAK", 15),
            "start_at": (self.now - timedelta(hours=4)).isoformat(),
            "end_at": (self.now + timedelta(hours=4)).isoformat(),
        }]
        self.record = AttendanceEntity(
            user_id=self.user_id, work_date=date(2026, 10, 12),
            clock_in_at=self.now - timedelta(hours=4),
            punch_metadata={"schedule_context": {"break_rules": self.rules}},
        )
        self.attendance_repo = SimpleNamespace(
            find_all=AsyncMock(return_value=[self.record]),
            update=AsyncMock(side_effect=lambda record: record),
        )
        employee = EmployeeEntity(employee_no="E1", first_name="Test", last_name="Employee", id=self.employee_id)
        uow = BreakUow({
            AttendanceEntity: self.attendance_repo,
            UserEntity: SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
                employee_id=self.employee_id, is_active=True, account_status="ACTIVE",
            ))),
            EmployeeEntity: SimpleNamespace(find_one=AsyncMock(return_value=employee)),
            FaceEnrollmentEntity: SimpleNamespace(find_all=AsyncMock(return_value=[
                SimpleNamespace(employee_id=self.employee_id, face_encoding=b"encoding"),
            ])),
        })
        face = SimpleNamespace(
            extract_face_encoding=Mock(return_value=b"encoding"),
            find_best_match=Mock(return_value=(self.employee_id, 0)),
        )
        self.use_case = RecordBreakUseCase(uow, face)

    async def punch(self, action):
        with patch("app.attendance.application.use_case.datetime", wraps=datetime) as clock:
            clock.now.return_value = self.now
            return await self.use_case._execute(RecordBreakInputDTO(
                user_id=self.user_id, image_bytes=b"image", break_type=action,
            ))

    async def test_configured_second_break_can_start_without_meal_break(self):
        await self.punch("second_break_out_at")
        self.assertEqual(self.record.second_break_out_at, self.now)
        self.attendance_repo.update.assert_awaited_once()

    async def test_break_start_outside_work_window_is_rejected(self):
        self.rules[0]["start_at"] = (self.now + timedelta(minutes=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "within its linked WORK"):
            await self.punch("second_break_out_at")
        self.attendance_repo.update.assert_not_awaited()

    async def test_break_end_updates_undertime_without_double_counting_previous_excess(self):
        self.record.second_break_out_at = self.now - timedelta(minutes=25)
        self.record.undertime_minutes = 13
        self.record.punch_metadata["break_calculation"] = {"excess_undertime_minutes": 3}
        await self.punch("second_break_in_at")
        self.assertEqual(self.record.undertime_minutes, 10)
        self.assertTrue(
            self.record.punch_metadata["break_calculation"]["undertime_excludes_break_excess"],
        )

    async def test_return_after_work_window_is_recorded_for_excess_calculation(self):
        self.record.second_break_out_at = self.now - timedelta(minutes=25)
        self.rules[0]["end_at"] = (self.now - timedelta(minutes=1)).isoformat()
        await self.punch("second_break_in_at")
        self.assertEqual(self.record.undertime_minutes, 0)

    async def test_second_break_rejected_if_meal_break_not_ended_when_meal_rule_exists(self):
        self.rules.append({
            **rule("MEAL_BREAK", 60, "UNPAID_BREAK"),
            "start_at": (self.now - timedelta(hours=4)).isoformat(),
            "end_at": (self.now + timedelta(hours=4)).isoformat(),
        })
        with self.assertRaisesRegex(ValueError, "after the meal break has ended"):
            await self.punch("second_break_out_at")

    async def test_first_break_allowed_after_meal_break_ended_when_meal_taken_first(self):
        self.rules.append({
            **rule("FIRST_BREAK", 15),
            "start_at": (self.now - timedelta(hours=4)).isoformat(),
            "end_at": (self.now + timedelta(hours=4)).isoformat(),
        })
        self.rules.append({
            **rule("MEAL_BREAK", 60, "UNPAID_BREAK"),
            "start_at": (self.now - timedelta(hours=4)).isoformat(),
            "end_at": (self.now + timedelta(hours=4)).isoformat(),
        })
        self.record.meal_break_out_at = self.now - timedelta(hours=1)
        self.record.meal_break_in_at = self.now - timedelta(minutes=15)
        # Second break is rejected because first break has not been taken yet
        with self.assertRaisesRegex(ValueError, "after the first break has ended"):
            await self.punch("second_break_out_at")

        # First break punch is allowed after meal break ends
        await self.punch("first_break_out_at")
        self.assertEqual(self.record.first_break_out_at, self.now)

    async def test_first_break_rejected_if_second_break_already_started(self):
        self.rules.append({
            **rule("FIRST_BREAK", 15),
            "start_at": (self.now - timedelta(hours=4)).isoformat(),
            "end_at": (self.now + timedelta(hours=4)).isoformat(),
        })
        self.record.second_break_out_at = self.now - timedelta(minutes=30)
        self.record.second_break_in_at = self.now - timedelta(minutes=15)
        with self.assertRaisesRegex(ValueError, "after the second break has started"):
            await self.punch("first_break_out_at")
