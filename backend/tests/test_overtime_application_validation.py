import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.attendance.infrastructure.router import (
    OvertimeApplicationInputSchema,
    _validate_overtime_application_period,
    _sync_attendance_overtime_from_applications,
    submit_overtime_application,
    get_overtime_attendance_options,
    _current_overtime_cutoff_statement,
    _validate_overtime_cutoff,
)
from app.core.database import init_db_models


class OvertimeApplicationInputTests(unittest.TestCase):
    def payload(self, **changes):
        return {
            "overtime_type": "REGULAR_OVERTIME", "requested_minutes": 30,
            "reason": "Completed assigned work", **changes,
        }

    def test_existing_clients_can_omit_both_timestamps(self):
        payload = OvertimeApplicationInputSchema(**self.payload())
        self.assertIsNone(payload.requested_start_at)
        self.assertIsNone(payload.requested_end_at)

    def test_accepts_overnight_philippine_period(self):
        payload = OvertimeApplicationInputSchema(**self.payload(
            requested_start_at="2026-10-12T23:30:00+08:00",
            requested_end_at="2026-10-13T00:30:00+08:00",
        ))
        self.assertEqual(payload.requested_start_at.utcoffset(), timedelta(hours=8))

    def test_rejects_partial_naive_and_reversed_periods(self):
        for fields in (
            {"requested_start_at": "2026-10-12T18:00:00+08:00"},
            {"requested_end_at": "2026-10-12T19:00:00+08:00"},
            {"requested_start_at": "2026-10-12T18:00:00", "requested_end_at": "2026-10-12T19:00:00"},
            {"requested_start_at": "2026-10-12T19:00:00+08:00", "requested_end_at": "2026-10-12T18:00:00+08:00"},
            {"requested_start_at": "2026-10-12T18:00:00+08:00", "requested_end_at": "2026-10-12T18:00:00+08:00"},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                OvertimeApplicationInputSchema(**self.payload(**fields))

    def test_night_differential_is_not_a_separate_employee_application(self):
        with self.assertRaisesRegex(ValidationError, "approved automatically"):
            OvertimeApplicationInputSchema(
                **self.payload(overtime_type="NIGHT_DIFFERENTIAL"),
            )


class AutomaticNightDifferentialTests(unittest.IsolatedAsyncioTestCase):
    async def test_application_sync_preserves_automatic_night_differential_approval(self):
        attendance = SimpleNamespace(
            id=uuid4(),
            regular_overtime_minutes=0,
            night_differential_overtime_minutes=0,
            night_differential_minutes=420,
            approved_regular_overtime_minutes=0,
            approved_night_differential_overtime_minutes=0,
            approved_night_differential_minutes=420,
            approved_night_diff=7,
        )
        session = MagicMock()
        session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: []))

        await _sync_attendance_overtime_from_applications(session, attendance)

        self.assertEqual(attendance.approved_night_differential_minutes, 420)
        self.assertEqual(attendance.approved_night_diff, 7)


class OvertimeApplicationSubmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        init_db_models()
        self.user_id = uuid4()
        self.attendance = SimpleNamespace(
            id=uuid4(), work_date=date(2026, 10, 12), overtime_request_status=None,
            regular_overtime_minutes=120,
            clock_in_at=datetime(2026, 10, 12, 0, tzinfo=timezone.utc),
            clock_out_at=datetime(2026, 10, 12, 12, tzinfo=timezone.utc),
            corrected_clock_in_at=datetime(2026, 10, 12, 1, tzinfo=timezone.utc),
            corrected_clock_out_at=datetime(2026, 10, 12, 11, tzinfo=timezone.utc),
            expected_clock_in_at=datetime(2026, 10, 12, 1, tzinfo=timezone.utc),
            expected_clock_out_at=datetime(2026, 10, 12, 9, tzinfo=timezone.utc),
            night_differential_overtime_minutes=0, night_differential_minutes=0,
        )
        self.employee = SimpleNamespace(
            id=uuid4(), employee_no="TEST", preferred_name=None,
            first_name="Test", middle_name=None, last_name="Employee", suffix=None,
        )
        self.session = MagicMock()
        self.session.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=(self.attendance, self.employee))))
        self.cutoff = SimpleNamespace(
            cutoff_code="OCT-1", period_start=date(2026, 10, 1), period_end=date(2026, 10, 15),
        )
        self.session.scalar = AsyncMock(side_effect=[self.cutoff, None, None])
        self.session.flush = AsyncMock()

        async def refresh(application):
            application.id = uuid4()
            application.payroll_posted = False

        self.session.refresh = AsyncMock(side_effect=refresh)
        self.uow = MagicMock()
        self.uow.__aenter__ = AsyncMock(return_value=SimpleNamespace(session=self.session))
        self.uow.__aexit__ = AsyncMock(return_value=False)

    async def submit(self, **changes):
        payload = OvertimeApplicationInputSchema(
            overtime_type="REGULAR_OVERTIME", requested_minutes=30, reason="Finished work",
            **changes,
        )
        with patch("app.attendance.infrastructure.router._sync_attendance_overtime_from_applications", new_callable=AsyncMock), \
             patch("app.attendance.infrastructure.router._queue_recent_attendance_refresh"), \
             patch("app.attendance.infrastructure.router.log_entity_action", new_callable=AsyncMock):
            return await submit_overtime_application(
                self.attendance.id, payload, claims={"sub": str(self.user_id)},
                uow=self.uow, es_client=None,
            )

    async def test_selected_period_is_persisted_and_returned_not_overwritten(self):
        result = await self.submit(
            requested_start_at="2026-10-12T18:00:00+08:00",
            requested_end_at="2026-10-12T18:30:00+08:00",
        )
        application = self.session.add.call_args.args[0]
        self.assertEqual(application.requested_start_at.hour, 18)
        self.assertEqual(application.requested_end_at.minute, 30)
        self.assertEqual(result.data.requested_start_at, application.requested_start_at)
        self.assertEqual(result.data.requested_end_at, application.requested_end_at)

    async def test_legacy_period_still_uses_expected_clock_out(self):
        result = await self.submit()
        self.assertEqual(result.data.requested_start_at, self.attendance.expected_clock_out_at)
        self.assertEqual(result.data.requested_end_at, self.attendance.corrected_clock_out_at)

    async def test_period_outside_corrected_punches_is_rejected_before_insert(self):
        with self.assertRaises(HTTPException) as error:
            await self.submit(
                requested_start_at="2026-10-12T18:00:00+08:00",
                requested_end_at="2026-10-12T20:00:00+08:00",
            )
        self.assertEqual(error.exception.status_code, 422)
        self.session.add.assert_not_called()

    async def test_minutes_exceeding_selected_period_are_rejected_before_insert(self):
        with self.assertRaises(HTTPException) as error:
            await self.submit(
                requested_start_at="2026-10-12T18:00:00+08:00",
                requested_end_at="2026-10-12T18:15:00+08:00",
            )
        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("cannot exceed the overtime application period", error.exception.detail)
        self.session.add.assert_not_called()

    async def test_submission_outside_current_cutoff_is_rejected(self):
        self.attendance.work_date = date(2026, 9, 30)
        with self.assertRaises(HTTPException) as error:
            await self.submit()
        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("current payroll cutoff", error.exception.detail)
        self.session.add.assert_not_called()

    async def test_missing_cutoff_does_not_fall_back_to_older_attendance(self):
        self.session.scalar.side_effect = [None]
        with self.assertRaises(HTTPException) as error:
            await self.submit()
        self.assertIn("Contact HR", error.exception.detail)
        self.session.add.assert_not_called()

    async def test_attendance_options_return_full_cutoff_not_five_recent_records(self):
        self.session.scalar.side_effect = [self.employee.id, self.cutoff]
        self.session.execute.return_value.scalars.return_value.all.return_value = [self.attendance] * 7
        result = await get_overtime_attendance_options(
            claims={"sub": str(self.user_id)}, uow=self.uow,
        )
        self.assertEqual(len(result.data.records), 7)
        self.assertEqual(result.data.cutoff.cutoff_code, "OCT-1")
        self.assertEqual(result.data.records[0].time_in, self.attendance.corrected_clock_in_at.isoformat())
        statement = str(self.session.execute.call_args.args[0])
        self.assertNotIn("LIMIT", statement)
        self.assertIn("work_date >=", statement)
        self.assertIn("work_date <=", statement)


class OvertimePayrollCutoffTests(unittest.TestCase):
    def test_cutoff_dates_are_inclusive(self):
        cutoff = SimpleNamespace(period_start=date(2026, 10, 1), period_end=date(2026, 10, 15))
        for work_date in (cutoff.period_start, cutoff.period_end):
            _validate_overtime_cutoff(cutoff, work_date)
        for work_date in (date(2026, 9, 30), date(2026, 10, 16)):
            with self.assertRaises(HTTPException):
                _validate_overtime_cutoff(cutoff, work_date)

    def test_cutoff_uses_current_active_employee_payroll_assignment(self):
        statement = _current_overtime_cutoff_statement(uuid4(), date(2026, 10, 12))
        sql = str(statement)
        self.assertIn("payroll_group_id", sql)
        self.assertIn("employee_id =", sql)
        self.assertIn("effective_from <=", sql)
        self.assertIn("effective_to >=", sql)
        self.assertIn("period_start <=", sql)
        self.assertIn("period_end >=", sql)
        self.assertIn("is_active IS true", sql)


class OvertimeApplicationPeriodValidationTests(unittest.TestCase):
    def setUp(self):
        self.actual_start = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
        self.actual_end = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)

    def test_accepts_period_matching_attendance_boundaries(self):
        _validate_overtime_application_period(
            requested_start_at=self.actual_start,
            requested_end_at=self.actual_end,
            actual_start_at=self.actual_start,
            actual_end_at=self.actual_end,
            requested_minutes=60,
        )

    def test_rejects_period_starting_before_actual_clock_in(self):
        with self.assertRaises(HTTPException) as error:
            _validate_overtime_application_period(
                requested_start_at=self.actual_start - timedelta(minutes=1),
                requested_end_at=self.actual_start + timedelta(minutes=60),
                actual_start_at=self.actual_start,
                actual_end_at=self.actual_end,
                requested_minutes=30,
            )

        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("within the effective", error.exception.detail)

    def test_rejects_period_ending_after_actual_clock_out(self):
        with self.assertRaises(HTTPException) as error:
            _validate_overtime_application_period(
                requested_start_at=self.actual_end - timedelta(minutes=60),
                requested_end_at=self.actual_end + timedelta(minutes=1),
                actual_start_at=self.actual_start,
                actual_end_at=self.actual_end,
                requested_minutes=30,
            )

        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("within the effective", error.exception.detail)

    def test_rejects_requested_minutes_longer_than_application_period(self):
        with self.assertRaises(HTTPException) as error:
            _validate_overtime_application_period(
                requested_start_at=self.actual_end - timedelta(minutes=30),
                requested_end_at=self.actual_end,
                actual_start_at=self.actual_start,
                actual_end_at=self.actual_end,
                requested_minutes=31,
            )

        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("cannot exceed the overtime application period", error.exception.detail)

    def test_rejects_invalid_attendance_punch_order(self):
        with self.assertRaises(HTTPException) as error:
            _validate_overtime_application_period(
                requested_start_at=self.actual_start,
                requested_end_at=self.actual_end,
                actual_start_at=self.actual_end,
                actual_end_at=self.actual_start,
                requested_minutes=60,
            )

        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("valid completed punch interval", error.exception.detail)
