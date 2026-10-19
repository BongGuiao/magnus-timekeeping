import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.attendance.application.use_case import ClockAttendanceUseCase
from app.filemaintenance.schedule.application import emergency_schedule_use_cases
from app.filemaintenance.schedule.infrastructure.emergency_schedule_db_model import (
    EmergencyScheduleRequestModel,
)


class EmergencyScheduleModelTests(unittest.TestCase):
    def test_request_is_auditable_and_unique_for_active_employee_date(self):
        table = EmergencyScheduleRequestModel.__table__

        self.assertEqual(table.schema, "schedule")
        self.assertIn("work_date", table.c)
        self.assertIn("schedule_template_id", table.c)
        self.assertIn("reviewed_by", table.c)
        active_day_index = next(
            index
            for index in table.indexes
            if index.name == "uq_emergency_schedule_requests_active_day"
        )
        self.assertTrue(active_day_index.unique)


class EmergencyScheduleResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_emergency_schedule_replaces_the_day_and_handles_overnight_shift(self):
        request_id, emergency_template_id = uuid4(), uuid4()
        assignment = SimpleNamespace(
            id=uuid4(),
            effective_from=date(2026, 10, 1),
            rest_day_pattern_id=uuid4(),
            schedule_template_id=uuid4(),
        )
        work_segment = SimpleNamespace(
            start_time=datetime.strptime("17:00", "%H:%M").time(),
            end_time=datetime.strptime("02:00", "%H:%M").time(),
            end_day_offset=1,
            flex_start_minutes=15,
        )

        class Rows:
            def first(self):
                return (assignment, 7)

        class ScalarRows:
            def __init__(self, rows):
                self.rows = rows

            def all(self):
                return self.rows

        session = SimpleNamespace(
            scalar=AsyncMock(side_effect=[
                SimpleNamespace(id=request_id, schedule_template_id=emergency_template_id),
                SimpleNamespace(is_workday=False, schedule_template_id=None),
            ]),
            execute=AsyncMock(return_value=Rows()),
            get=AsyncMock(return_value=SimpleNamespace(
                grace_minutes=5,
                ot_eligible=True,
                minimum_ot_minutes=30,
                pre_shift_ot_allowed=False,
                schedule_code="EMERGENCY",
            )),
            scalars=AsyncMock(side_effect=[
                ScalarRows([work_segment]),
                ScalarRows([]),
            ]),
        )
        use_case = ClockAttendanceUseCase(
            SimpleNamespace(session=session),
            face_recognition_service=None,
        )

        result = await use_case._resolve_schedule_day(
            SimpleNamespace(session=session),
            uuid4(),
            date(2026, 10, 22),
        )

        self.assertEqual(result.schedule_template_id, emergency_template_id)
        self.assertEqual(result.work_type, "REG")
        self.assertEqual(result.expected_clock_in_at.isoformat(), "2026-10-22T17:00:00+08:00")
        self.assertEqual(result.expected_clock_out_at.isoformat(), "2026-10-23T02:00:00+08:00")
        self.assertEqual(result.schedule_context["emergency_schedule_request_id"], str(request_id))

    async def test_retroactive_filing_allows_seven_days_and_requires_open_cutoff(self):
        with (
            patch.object(
                emergency_schedule_use_cases,
                "utc_now",
                return_value=datetime(2026, 10, 18, 13, tzinfo=timezone.utc),
            ),
            patch.object(
                emergency_schedule_use_cases,
                "_require_current_open_unprocessed_cutoff",
                new_callable=AsyncMock,
            ) as require_cutoff,
        ):
            accepted = await emergency_schedule_use_cases._validate_retroactive_work_date(
                SimpleNamespace(), uuid4(), date(2026, 10, 11)
            )
            self.assertTrue(accepted)
            require_cutoff.assert_awaited_once()
            with self.assertRaisesRegex(ValueError, "up to 7 days"):
                await emergency_schedule_use_cases._validate_retroactive_work_date(
                    SimpleNamespace(), uuid4(), date(2026, 10, 10)
                )

    async def test_current_and_future_emergency_dates_do_not_require_retroactive_cutoff(self):
        with (
            patch.object(
                emergency_schedule_use_cases,
                "utc_now",
                return_value=datetime(2026, 10, 18, 13, tzinfo=timezone.utc),
            ),
            patch.object(
                emergency_schedule_use_cases,
                "_require_current_open_unprocessed_cutoff",
                new_callable=AsyncMock,
            ) as require_cutoff,
        ):
            for work_date in (date(2026, 10, 18), date(2026, 10, 19)):
                accepted = await emergency_schedule_use_cases._validate_retroactive_work_date(
                    SimpleNamespace(), uuid4(), work_date
                )
                self.assertFalse(accepted)
            require_cutoff.assert_not_awaited()

    async def test_retroactive_request_requires_an_unprocessed_current_cutoff(self):
        payroll_group_id, cutoff_id = uuid4(), uuid4()
        cutoff = SimpleNamespace(
            id=cutoff_id,
            locked_at=None,
            status="SCHEDULED",
        )

        class ScalarRows:
            def __init__(self, rows):
                self.rows = rows

            def all(self):
                return self.rows

        session = SimpleNamespace(
            scalars=AsyncMock(side_effect=[
                ScalarRows([payroll_group_id]),
                ScalarRows([cutoff]),
            ]),
            scalar=AsyncMock(return_value=None),
        )
        await emergency_schedule_use_cases._require_current_open_unprocessed_cutoff(
            SimpleNamespace(session=session),
            uuid4(),
            date(2026, 10, 17),
            date(2026, 10, 18),
        )

        session.scalar.assert_awaited_once()

    async def test_retroactive_request_rejects_a_processed_cutoff(self):
        payroll_group_id, cutoff_id = uuid4(), uuid4()
        cutoff = SimpleNamespace(
            id=cutoff_id,
            locked_at=None,
            status="SCHEDULED",
        )

        class ScalarRows:
            def __init__(self, rows):
                self.rows = rows

            def all(self):
                return self.rows

        session = SimpleNamespace(
            scalars=AsyncMock(side_effect=[
                ScalarRows([payroll_group_id]),
                ScalarRows([cutoff]),
            ]),
            scalar=AsyncMock(return_value=uuid4()),
        )
        with self.assertRaisesRegex(ValueError, "already been processed"):
            await emergency_schedule_use_cases._require_current_open_unprocessed_cutoff(
                SimpleNamespace(session=session),
                uuid4(),
                date(2026, 10, 17),
                date(2026, 10, 18),
            )
