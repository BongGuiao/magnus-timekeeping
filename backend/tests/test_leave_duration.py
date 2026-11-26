import unittest
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.filemaintenance.leaves.application import leave_duration
from app.filemaintenance.leaves.application import leave_records_use_case

TZ = leave_duration.MANILA


def schedule(day, rest=False, overnight=False):
    return SimpleNamespace(
        work_type="REST" if rest else "REG",
        schedule_template_id=uuid4(),
        expected_clock_in_at=datetime.combine(day, time(22 if overnight else 9), tzinfo=TZ),
        expected_clock_out_at=datetime.combine(day + timedelta(days=1 if overnight else 0), time(6 if overnight else 18), tzinfo=TZ),
        schedule_context={"schedule_assignment_id": "test"},
    )


def segment(kind, start, end, *, offset=0, slot=None, minutes=0):
    return SimpleNamespace(
        segment_type=kind, start_time=start, end_time=end, end_day_offset=offset,
        break_slot=slot, break_minutes=minutes,
    )


class LeaveDurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_holidays_rest_days_and_unpaid_break_are_excluded(self):
        first = date(2026, 12, 21)
        segments = [
            segment("WORK", time(9), time(18)),
            segment("UNPAID_BREAK", time(9), time(18), slot="MEAL_BREAK", minutes=60),
        ]
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=uuid4()),
            scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: segments)),
        )

        async def resolve_schedule(_session, _employee, day):
            if day < first:
                return SimpleNamespace(schedule_context=None)
            return schedule(day, rest=day == first + timedelta(days=1))

        async def resolve_holiday(_session, _employee, day):
            return "RH" if day == first + timedelta(days=2) else "REG"

        with patch.object(leave_duration, "resolve_schedule_day", new=AsyncMock(side_effect=resolve_schedule)), \
                patch.object(leave_duration, "resolve_attendance_day_type", new=AsyncMock(side_effect=resolve_holiday)):
            result = await leave_duration.calculate_leave_duration(
                session, uuid4(), datetime(2026, 12, 21, 9, tzinfo=TZ),
                datetime(2026, 12, 24, 18, tzinfo=TZ),
            )
        self.assertEqual(result.requested_minutes, 960)
        self.assertEqual([day.work_date for day in result.days], [first, first + timedelta(days=3)])
        self.assertEqual(result.rest_days, (first + timedelta(days=1),))
        self.assertEqual(result.holidays, (first + timedelta(days=2),))

    async def test_partial_shift_does_not_deduct_unscheduled_break(self):
        day = date(2026, 12, 21)
        segments = [
            segment("WORK", time(9), time(18)),
            segment("UNPAID_BREAK", time(9), time(18), slot="MEAL_BREAK", minutes=60),
        ]
        self.assertEqual(leave_duration._covered_minutes(
            datetime(2026, 12, 21, 9, tzinfo=TZ), datetime(2026, 12, 21, 13, tzinfo=TZ),
            day, segments, datetime(2026, 12, 21, 9, tzinfo=TZ), datetime(2026, 12, 21, 18, tzinfo=TZ),
        ), 240)

    async def test_overnight_uses_shift_start_date_for_holiday(self):
        start_day = date(2026, 12, 21)
        segments = [segment("WORK", time(22), time(6), offset=1)]
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=uuid4()),
            scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: segments)),
        )

        async def resolve_schedule(_session, _employee, day):
            if day == start_day:
                return schedule(day, overnight=True)
            if day == start_day + timedelta(days=1):
                return schedule(day, rest=True)
            return SimpleNamespace(schedule_context=None)

        with patch.object(leave_duration, "resolve_schedule_day", new=AsyncMock(side_effect=resolve_schedule)), \
                patch.object(leave_duration, "resolve_attendance_day_type", new=AsyncMock(return_value="RH")):
            result = await leave_duration.calculate_leave_duration(
                session, uuid4(), datetime(2026, 12, 21, 22, tzinfo=TZ),
                datetime(2026, 12, 22, 6, tzinfo=TZ),
            )
        self.assertEqual(result.requested_minutes, 0)
        self.assertEqual(result.holidays, (start_day,))

    async def test_missing_work_location_treats_the_date_as_an_ordinary_workday(self):
        day = date(2026, 12, 21)
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=None),
            scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [segment("WORK", time(9), time(18))])),
        )
        async def resolve_schedule(_session, _employee, work_date):
            return schedule(day) if work_date == day else SimpleNamespace(schedule_context=None)
        with patch.object(leave_duration, "resolve_schedule_day", new=AsyncMock(side_effect=resolve_schedule)), \
                patch.object(leave_duration, "resolve_attendance_day_type", new=AsyncMock()) as holiday:
            result = await leave_duration.calculate_leave_duration(
                session, uuid4(), datetime(2026, 12, 21, 9, tzinfo=TZ),
                datetime(2026, 12, 21, 18, tzinfo=TZ),
            )
        self.assertEqual(result.requested_minutes, 480)
        holiday.assert_not_awaited()

    async def test_daily_cap_is_applied_before_summing_multiple_workdays(self):
        first = date(2026, 11, 27)
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=uuid4()),
            scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [segment("WORK", time(9), time(18))])),
        )

        async def resolve_schedule(_session, _employee, day):
            return schedule(day) if day >= first else SimpleNamespace(schedule_context=None)

        with patch.object(leave_duration, "resolve_schedule_day", new=AsyncMock(side_effect=resolve_schedule)), \
                patch.object(leave_duration, "resolve_attendance_day_type", new=AsyncMock(return_value="REG")):
            result = await leave_duration.calculate_leave_duration(
                session, uuid4(), datetime(2026, 11, 27, 9, tzinfo=TZ),
                datetime(2026, 11, 29, 13, tzinfo=TZ),
            )
        self.assertEqual([day.requested_minutes for day in result.days], [480, 480, 240])
        self.assertEqual(result.requested_minutes, 1200)

    async def test_nine_hour_overnight_shift_is_one_leave_day(self):
        start = datetime(2026, 11, 27, 22, tzinfo=TZ)
        end = datetime(2026, 11, 28, 7, tzinfo=TZ)
        self.assertEqual(leave_duration._covered_minutes(
            start, end, start.date(), [segment("WORK", time(22), time(7), offset=1)], start, end,
        ), 480)

    async def test_missing_schedule_and_cross_year_are_rejected(self):
        missing = SimpleNamespace(schedule_context=None)
        with patch.object(leave_duration, "resolve_schedule_day", new=AsyncMock(return_value=missing)):
            with self.assertRaisesRegex(ValueError, "No approved schedule"):
                await leave_duration.calculate_leave_duration(
                    object(), uuid4(), datetime(2026, 12, 21, 9, tzinfo=TZ), datetime(2026, 12, 21, 18, tzinfo=TZ),
                )
        with self.assertRaisesRegex(ValueError, "separate leave applications"):
            await leave_duration.calculate_leave_duration(
                object(), uuid4(), datetime(2026, 12, 31, 9, tzinfo=TZ), datetime(2027, 1, 1, 18, tzinfo=TZ),
            )

    async def test_approval_charges_balance_and_allocates_paid_days_first(self):
        first = date(2026, 12, 21)
        application = SimpleNamespace(
            id=uuid4(), employee_id=uuid4(), leave_type_id=uuid4(), application_no="LV-1",
            start_at=datetime(2026, 12, 21, 9, tzinfo=TZ),
            end_at=datetime(2026, 12, 23, 18, tzinfo=TZ),
            requested_minutes=960, paid_minutes=None, unpaid_minutes=None,
        )
        entitlement = SimpleNamespace(
            opening_minutes=600, granted_minutes=0, accrued_minutes=0, carryover_minutes=0,
            adjustment_minutes=0, used_minutes=0, reserved_minutes=0, expired_minutes=0,
            converted_minutes=0, available_minutes=600, last_calculated_at=None,
        )
        rows = [
            SimpleNamespace(leave_date=first, requested_minutes=480),
            SimpleNamespace(leave_date=first + timedelta(days=2), requested_minutes=480),
        ]
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: None),
                SimpleNamespace(scalar_one_or_none=lambda: entitlement),
            ]),
            scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: rows)),
            add=lambda row: None,
        )
        duration = leave_duration.LeaveDuration(
            tuple(leave_duration.LeaveDurationDay(row.leave_date, 480) for row in rows), (), (),
        )
        with patch.object(leave_records_use_case, "calculate_leave_duration", new=AsyncMock(return_value=duration)), \
                patch.object(leave_records_use_case, "_require_duration_open", new=AsyncMock()):
            await leave_records_use_case._post_approved_leave_charge(session, application, uuid4())
        self.assertEqual((application.paid_minutes, application.unpaid_minutes), (600, 360))
        self.assertEqual((entitlement.used_minutes, entitlement.available_minutes), (600, 0))
        self.assertEqual([(row.approved_paid_minutes, row.approved_unpaid_minutes) for row in rows], [
            (480, 0), (120, 360),
        ])

    async def test_changed_schedule_cannot_silently_change_approval_charge(self):
        app = SimpleNamespace(
            employee_id=uuid4(), start_at=datetime(2026, 12, 21, 9, tzinfo=TZ),
            end_at=datetime(2026, 12, 21, 18, tzinfo=TZ), requested_minutes=480,
        )
        duration = leave_duration.LeaveDuration((leave_duration.LeaveDurationDay(date(2026, 12, 21), 240),), (), ())
        with patch.object(leave_records_use_case, "calculate_leave_duration", new=AsyncMock(return_value=duration)):
            with self.assertRaisesRegex(ValueError, "240 minutes"):
                await leave_records_use_case._validated_duration(
                    object(), app.employee_id, app.start_at, app.end_at, app.requested_minutes,
                )

    async def test_filing_deadline_includes_overnight_shift_work_date(self):
        employee_id = uuid4()
        work_date = date(2026, 12, 15)
        duration = leave_duration.LeaveDuration((leave_duration.LeaveDurationDay(work_date, 300),), (), ())
        with patch.object(leave_records_use_case, "require_attendance_open", new=AsyncMock()) as guard:
            await leave_records_use_case._require_duration_open(object(), employee_id, duration, "FILING")
        self.assertEqual(guard.await_args.args[1:], (employee_id, work_date, work_date))
        self.assertEqual(guard.await_args.kwargs["stage"], "FILING")

    async def test_draft_day_update_preserves_manually_maintained_metadata(self):
        work_date = date(2026, 12, 15)
        row = SimpleNamespace(
            leave_date=work_date, requested_minutes=480, roster_id=uuid4(), approved_paid_minutes=0,
            approved_unpaid_minutes=0, attendance_overlap_minutes=0, final_charge_minutes=0,
            holiday_flag=False, rest_day_flag=False,
        )
        session = SimpleNamespace(
            scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])),
            execute=AsyncMock(),
        )
        same = leave_duration.LeaveDuration((leave_duration.LeaveDurationDay(work_date, 480),), (), ())
        await leave_records_use_case._replace_draft_days(session, uuid4(), same)
        session.execute.assert_not_awaited()
        changed = leave_duration.LeaveDuration((leave_duration.LeaveDurationDay(work_date, 240),), (), ())
        with self.assertRaisesRegex(ValueError, "manually maintained"):
            await leave_records_use_case._replace_draft_days(session, uuid4(), changed)
        session.execute.assert_not_awaited()
