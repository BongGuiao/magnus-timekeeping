import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.attendance.application.overtime_use_cases import (
    DecideOvertimeApplicationInput,
    DecideOvertimeApplicationUseCase,
    GetOvertimeAttendanceOptionsInput,
    GetOvertimeAttendanceOptionsUseCase,
    SubmitOvertimeApplicationInput,
    SubmitOvertimeApplicationUseCase,
)
from app.attendance.domain import overtime_rules as rules
from app.attendance.domain.entities.attendance_employee import AttendanceEmployee
from app.attendance.domain.entities.overtime import (
    OvertimeApplication,
    OvertimeApplicationRecord,
    OvertimeAttendance,
    OvertimeCutoff,
)
from app.attendance.domain.exceptions import (
    ConflictError,
    PermissionDeniedError,
    RecordNotFoundError,
    RuleViolationError,
)
from app.attendance.infrastructure.overtime_repository import (
    SqlAlchemyOvertimeRepository,
    current_overtime_cutoff_statement,
)
from app.attendance.infrastructure.overtime_router import submit_overtime_application
from app.attendance.infrastructure.overtime_schemas import OvertimeApplicationInputSchema
from app.core.database import init_db_models

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


def make_attendance(**changes) -> OvertimeAttendance:
    values = dict(
        id=uuid4(), user_id=uuid4(), work_date=date(2026, 10, 12),
        regular_overtime_minutes=120,
        clock_in_at=datetime(2026, 10, 12, 0, tzinfo=timezone.utc),
        clock_out_at=datetime(2026, 10, 12, 12, tzinfo=timezone.utc),
        corrected_clock_in_at=datetime(2026, 10, 12, 1, tzinfo=timezone.utc),
        corrected_clock_out_at=datetime(2026, 10, 12, 11, tzinfo=timezone.utc),
        expected_clock_in_at=datetime(2026, 10, 12, 1, tzinfo=timezone.utc),
        expected_clock_out_at=datetime(2026, 10, 12, 9, tzinfo=timezone.utc),
    )
    values.update(changes)
    return OvertimeAttendance(**values)


def make_employee() -> AttendanceEmployee:
    return AttendanceEmployee(id=uuid4(), employee_no="TEST", first_name="Test", last_name="Employee")


class FakeOvertimeRepository:
    def __init__(self, attendance=None, employee=None, cutoff=None):
        self.attendance = attendance
        self.employee = employee or make_employee()
        self.cutoff = cutoff
        self.applications: list[OvertimeApplication] = []
        self.pending_record: OvertimeApplicationRecord | None = None
        self.supervisor_scope = "unset"
        self.saved_attendance = None
        self.employee_user_id = uuid4()

    async def get_active_employee_id_for_user(self, user_id):
        return self.employee.id

    async def get_user_id_for_employee(self, employee_id):
        return self.employee_user_id

    async def get_current_cutoff(self, employee_id, today):
        return self.cutoff

    async def list_completed_attendance_in_period(self, user_id, period_start, period_end):
        self.period = (period_start, period_end)
        return [self.attendance] * 7

    async def lock_completed_attendance(self, attendance_id, user_id):
        return (self.attendance, self.employee) if self.attendance is not None else None

    async def has_open_application(self, attendance_id, overtime_type=None):
        return any(
            app.status in rules.OPEN_APPLICATION_STATUSES
            and (overtime_type is None or app.overtime_type == overtime_type)
            for app in self.applications
        )

    async def add_application(self, application):
        application.id = uuid4()
        self.applications.append(application)
        return application

    async def save_application(self, application):
        self.saved_application = application

    async def save_attendance(self, attendance):
        self.saved_attendance = attendance

    async def list_applications_for_attendance(self, attendance_id):
        return list(reversed(self.applications))

    async def list_applications_for_user(self, user_id):
        return []

    async def list_pending_applications(self, supervisor_employee_id):
        return []

    async def lock_pending_application(self, application_id, supervisor_employee_id):
        self.supervisor_scope = supervisor_employee_id
        return self.pending_record


class FakeUnitOfWork:
    def __init__(self, repository):
        self.overtime = repository
        self.exit_exception = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.exit_exception = exc_type


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
            OvertimeApplicationInputSchema(**self.payload(overtime_type="NIGHT_DIFFERENTIAL"))


class OvertimeTotalsTests(unittest.TestCase):
    def application(self, overtime_type, status, minutes=30, final=None):
        return OvertimeApplication(
            application_no="OT", employee_id=uuid4(), attendance_record_id=uuid4(),
            attendance_date=date(2026, 10, 12), requested_start_at=NOW, requested_end_at=NOW,
            potential_ot_minutes=minutes, requested_minutes=minutes, overtime_type=overtime_type,
            reason="r", status=status, final_payable_minutes=final,
        )

    def test_preserves_automatic_night_differential_approval(self):
        attendance = make_attendance(
            regular_overtime_minutes=0, night_differential_minutes=420,
            approved_night_differential_minutes=420, approved_night_diff=7,
        )
        rules.apply_application_totals(attendance, [])
        self.assertEqual(attendance.approved_night_differential_minutes, 420)
        self.assertEqual(attendance.approved_night_diff, 7)
        self.assertIsNone(attendance.overtime_request_status)

    def test_pending_beats_approved_and_only_approved_minutes_are_payable(self):
        attendance = make_attendance(night_differential_overtime_minutes=60)
        rules.apply_application_totals(attendance, [
            self.application("NIGHT_DIFFERENTIAL_OVERTIME", "PENDING"),
            self.application("REGULAR_OVERTIME", "APPROVED", minutes=30, final=20),
        ])
        self.assertEqual(attendance.overtime_request_status, "PENDING")
        self.assertEqual(attendance.approved_regular_overtime_minutes, 20)
        self.assertEqual(attendance.approved_night_differential_overtime_minutes, 0)
        self.assertEqual(attendance.requested_night_differential_overtime_minutes, 30)
        self.assertAlmostEqual(attendance.approved_ot_worked, 20 / 60)

    def test_only_the_newest_application_per_type_counts(self):
        attendance = make_attendance()
        rules.apply_application_totals(attendance, [
            self.application("REGULAR_OVERTIME", "REJECTED", minutes=45),
            self.application("REGULAR_OVERTIME", "APPROVED", minutes=30, final=30),
        ])
        self.assertEqual(attendance.overtime_request_status, "REJECTED")
        self.assertEqual(attendance.requested_regular_overtime_minutes, 45)
        self.assertEqual(attendance.approved_regular_overtime_minutes, 0)


class SubmitOvertimeApplicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id = uuid4()
        self.attendance = make_attendance(user_id=self.user_id)
        self.cutoff = OvertimeCutoff("OCT-1", date(2026, 10, 1), date(2026, 10, 15))
        self.repository = FakeOvertimeRepository(self.attendance, cutoff=self.cutoff)
        self.uow = FakeUnitOfWork(self.repository)
        self.refresher = MagicMock()
        self.audit = MagicMock(record=AsyncMock())
        self.use_case = SubmitOvertimeApplicationUseCase(
            self.uow, self.refresher, self.audit, clock=lambda: NOW,
        )

    async def submit(self, **changes):
        values = dict(
            user_id=self.user_id, attendance_id=self.attendance.id,
            overtime_type="REGULAR_OVERTIME", requested_minutes=30, reason="Finished work",
        )
        values.update(changes)
        return await self.use_case.execute(SubmitOvertimeApplicationInput(**values))

    def assertNothingPersisted(self):
        self.assertEqual(self.repository.applications, [])
        self.refresher.request_refresh.assert_not_called()
        self.audit.record.assert_not_awaited()

    async def test_selected_period_is_persisted_and_returned_not_overwritten(self):
        start = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)
        end = datetime(2026, 10, 12, 10, 30, tzinfo=timezone.utc)
        record = await self.submit(requested_start_at=start, requested_end_at=end)
        saved = self.repository.applications[0]
        self.assertEqual((saved.requested_start_at, saved.requested_end_at), (start, end))
        self.assertEqual(record.application.requested_start_at, start)
        self.assertEqual(record.application.requested_end_at, end)

    async def test_legacy_period_still_uses_expected_clock_out(self):
        record = await self.submit()
        self.assertEqual(record.application.requested_start_at, self.attendance.expected_clock_out_at)
        self.assertEqual(record.application.requested_end_at, self.attendance.corrected_clock_out_at)

    async def test_success_updates_attendance_summary_and_notifies(self):
        record = await self.submit()
        self.assertIs(self.repository.saved_attendance, self.attendance)
        self.assertEqual(self.attendance.overtime_request_status, "PENDING")
        self.assertEqual(self.attendance.requested_regular_overtime_minutes, 30)
        self.assertEqual(self.attendance.overtime_requested_at, NOW)
        self.assertEqual(record.application.status, "PENDING")
        self.refresher.request_refresh.assert_called_once_with(self.user_id)
        self.audit.record.assert_awaited_once()
        self.assertEqual(self.audit.record.await_args.kwargs["action"], "SUBMIT")

    async def test_period_outside_corrected_punches_is_rejected_before_insert(self):
        with self.assertRaises(RuleViolationError):
            await self.submit(
                requested_start_at=datetime(2026, 10, 12, 10, tzinfo=timezone.utc),
                requested_end_at=datetime(2026, 10, 12, 12, tzinfo=timezone.utc),
            )
        self.assertNothingPersisted()

    async def test_minutes_exceeding_selected_period_are_rejected_before_insert(self):
        with self.assertRaisesRegex(RuleViolationError, "cannot exceed the overtime application period"):
            await self.submit(
                requested_start_at=datetime(2026, 10, 12, 10, tzinfo=timezone.utc),
                requested_end_at=datetime(2026, 10, 12, 10, 15, tzinfo=timezone.utc),
            )
        self.assertNothingPersisted()

    async def test_submission_outside_current_cutoff_is_rejected(self):
        self.attendance.work_date = date(2026, 9, 30)
        with self.assertRaisesRegex(RuleViolationError, "current payroll cutoff"):
            await self.submit()
        self.assertNothingPersisted()

    async def test_missing_cutoff_does_not_fall_back_to_older_attendance(self):
        self.repository.cutoff = None
        with self.assertRaisesRegex(RuleViolationError, "Contact HR"):
            await self.submit()
        self.assertNothingPersisted()

    async def test_unknown_attendance_is_not_found(self):
        self.repository.attendance = None
        with self.assertRaises(RecordNotFoundError):
            await self.submit()

    async def test_second_open_application_of_same_type_conflicts(self):
        await self.submit()
        with self.assertRaisesRegex(ConflictError, "already has a pending or approved"):
            await self.submit()
        self.assertEqual(len(self.repository.applications), 1)

    async def test_failure_exits_unit_of_work_with_the_error_so_it_rolls_back(self):
        self.repository.cutoff = None
        with self.assertRaises(RuleViolationError):
            await self.submit()
        self.assertIs(self.uow.exit_exception, RuleViolationError)

    async def test_requested_minutes_cannot_exceed_calculated_minutes(self):
        with self.assertRaisesRegex(RuleViolationError, "calculated 120 minutes"):
            await self.submit(requested_minutes=121)

    async def test_http_router_translates_domain_errors(self):
        payload = OvertimeApplicationInputSchema(
            overtime_type="REGULAR_OVERTIME", requested_minutes=30, reason="Finished work",
        )
        for error, status_code in (
            (RecordNotFoundError("missing"), 404),
            (ConflictError("duplicate"), 409),
            (PermissionDeniedError("nope"), 403),
            (RuleViolationError("invalid"), 422),
        ):
            with self.subTest(error=type(error).__name__):
                use_case = MagicMock(execute=AsyncMock(side_effect=error))
                with self.assertRaises(HTTPException) as raised:
                    await submit_overtime_application(
                        self.attendance.id, payload,
                        claims={"sub": str(self.user_id)}, use_case=use_case,
                    )
                self.assertEqual(raised.exception.status_code, status_code)
                self.assertEqual(raised.exception.detail, str(error))


class DecideOvertimeApplicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.employee = make_employee()
        self.attendance = make_attendance()
        self.application = OvertimeApplication(
            id=uuid4(), application_no="OT-1", employee_id=self.employee.id,
            attendance_record_id=self.attendance.id, attendance_date=self.attendance.work_date,
            requested_start_at=NOW, requested_end_at=NOW, potential_ot_minutes=120,
            requested_minutes=60, overtime_type="REGULAR_OVERTIME", reason="r", status="PENDING",
        )
        self.repository = FakeOvertimeRepository(self.attendance, self.employee)
        self.repository.applications = [self.application]
        self.repository.pending_record = OvertimeApplicationRecord(
            self.application, self.attendance, self.employee,
        )
        self.refresher = MagicMock()
        self.audit = MagicMock(record=AsyncMock())
        self.use_case = DecideOvertimeApplicationUseCase(
            FakeUnitOfWork(self.repository), self.refresher, self.audit, clock=lambda: NOW,
        )
        self.supervisor_employee_id = uuid4()

    async def decide(self, decision="APPROVED", minutes=45, **changes):
        values = dict(
            application_id=self.application.id, actor_id=uuid4(),
            actor_employee_id=self.supervisor_employee_id, is_admin=False,
            decision=decision, supervisor_approved_minutes=minutes,
        )
        values.update(changes)
        return await self.use_case.execute(DecideOvertimeApplicationInput(**values))

    async def test_approval_records_minutes_and_updates_attendance_totals(self):
        record = await self.decide()
        self.assertEqual(record.application.status, "APPROVED")
        self.assertEqual(record.application.final_payable_minutes, 45)
        self.assertEqual(record.application.row_version, 2)
        self.assertEqual(self.attendance.approved_regular_overtime_minutes, 45)
        self.assertEqual(self.attendance.overtime_request_status, "APPROVED")
        self.assertEqual(self.attendance.overtime_approved_at, NOW)
        self.assertIs(self.repository.saved_application, self.application)
        self.refresher.request_refresh.assert_called_once_with(self.repository.employee_user_id)
        self.assertEqual(self.audit.record.await_args.kwargs["action"], "APPROVED")

    async def test_rejection_requires_zero_minutes_and_pays_nothing(self):
        with self.assertRaisesRegex(RuleViolationError, "zero approved minutes"):
            await self.decide("REJECTED", minutes=10)
        record = await self.decide("REJECTED", minutes=0)
        self.assertEqual(record.application.final_payable_minutes, 0)
        self.assertEqual(self.attendance.approved_regular_overtime_minutes, 0)

    async def test_approval_minutes_must_be_positive_and_within_request(self):
        with self.assertRaisesRegex(RuleViolationError, "positive"):
            await self.decide(minutes=0)
        with self.assertRaisesRegex(RuleViolationError, "cannot exceed the requested"):
            await self.decide(minutes=61)

    async def test_supervisors_cannot_decide_their_own_application(self):
        with self.assertRaises(PermissionDeniedError):
            await self.decide(actor_employee_id=self.employee.id)
        self.refresher.request_refresh.assert_not_called()

    async def test_supervisor_is_scoped_to_their_team_but_admin_is_not(self):
        await self.decide()
        self.assertEqual(self.repository.supervisor_scope, self.supervisor_employee_id)
        self.application.status = "PENDING"
        await self.decide(is_admin=True)
        self.assertIsNone(self.repository.supervisor_scope)

    async def test_missing_pending_application_is_not_found(self):
        self.repository.pending_record = None
        with self.assertRaises(RecordNotFoundError):
            await self.decide()


class OvertimeAttendanceOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_options_return_every_record_in_the_current_cutoff(self):
        cutoff = OvertimeCutoff("OCT-1", date(2026, 10, 1), date(2026, 10, 15))
        repository = FakeOvertimeRepository(make_attendance(), cutoff=cutoff)
        use_case = GetOvertimeAttendanceOptionsUseCase(FakeUnitOfWork(repository), clock=lambda: NOW)

        options = await use_case.execute(GetOvertimeAttendanceOptionsInput(user_id=uuid4()))

        self.assertEqual(len(options.attendance), 7)
        self.assertEqual(options.cutoff.cutoff_code, "OCT-1")
        self.assertEqual(repository.period, (cutoff.period_start, cutoff.period_end))

    async def test_missing_cutoff_is_reported_instead_of_listing_old_attendance(self):
        repository = FakeOvertimeRepository(make_attendance(), cutoff=None)
        use_case = GetOvertimeAttendanceOptionsUseCase(FakeUnitOfWork(repository), clock=lambda: NOW)
        with self.assertRaisesRegex(RuleViolationError, "Contact HR"):
            await use_case.execute(GetOvertimeAttendanceOptionsInput(user_id=uuid4()))


class OvertimePayrollCutoffTests(unittest.TestCase):
    def test_cutoff_dates_are_inclusive(self):
        cutoff = OvertimeCutoff("C", date(2026, 10, 1), date(2026, 10, 15))
        for work_date in (cutoff.period_start, cutoff.period_end):
            rules.validate_cutoff(cutoff, work_date)
        for work_date in (date(2026, 9, 30), date(2026, 10, 16)):
            with self.assertRaises(RuleViolationError):
                rules.validate_cutoff(cutoff, work_date)

    def test_cutoff_uses_current_active_employee_payroll_assignment(self):
        init_db_models()
        sql = str(current_overtime_cutoff_statement(uuid4(), date(2026, 10, 12)))
        for fragment in (
            "payroll_group_id", "employee_id =", "effective_from <=", "effective_to >=",
            "period_start <=", "period_end >=", "is_active IS true",
        ):
            self.assertIn(fragment, sql)


class SqlAlchemyOvertimeRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_attendance_options_query_covers_the_whole_cutoff_without_a_limit(self):
        init_db_models()
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=SimpleNamespace(all=lambda: [])))
        )
        await SqlAlchemyOvertimeRepository(session).list_completed_attendance_in_period(
            uuid4(), date(2026, 10, 1), date(2026, 10, 15),
        )
        statement = str(session.execute.call_args.args[0])
        self.assertNotIn("LIMIT", statement)
        self.assertIn("work_date >=", statement)
        self.assertIn("work_date <=", statement)


class OvertimeApplicationPeriodValidationTests(unittest.TestCase):
    def setUp(self):
        self.actual_start = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
        self.actual_end = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)

    def validate(self, **changes):
        values = dict(
            requested_start_at=self.actual_start, requested_end_at=self.actual_end,
            actual_start_at=self.actual_start, actual_end_at=self.actual_end, requested_minutes=60,
        )
        values.update(changes)
        rules.validate_application_period(**values)

    def test_accepts_period_matching_attendance_boundaries(self):
        self.validate()

    def test_rejects_period_starting_before_actual_clock_in(self):
        with self.assertRaisesRegex(RuleViolationError, "within the effective"):
            self.validate(
                requested_start_at=self.actual_start - timedelta(minutes=1),
                requested_end_at=self.actual_start + timedelta(minutes=60), requested_minutes=30,
            )

    def test_rejects_period_ending_after_actual_clock_out(self):
        with self.assertRaisesRegex(RuleViolationError, "within the effective"):
            self.validate(
                requested_start_at=self.actual_end - timedelta(minutes=60),
                requested_end_at=self.actual_end + timedelta(minutes=1), requested_minutes=30,
            )

    def test_rejects_requested_minutes_longer_than_application_period(self):
        with self.assertRaisesRegex(RuleViolationError, "cannot exceed the overtime application period"):
            self.validate(
                requested_start_at=self.actual_end - timedelta(minutes=30), requested_minutes=31,
            )

    def test_rejects_invalid_attendance_punch_order(self):
        with self.assertRaisesRegex(RuleViolationError, "valid completed punch interval"):
            self.validate(actual_start_at=self.actual_end, actual_end_at=self.actual_start)
