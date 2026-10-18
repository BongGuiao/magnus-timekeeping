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
    RecalculateAttendanceRangeInput,
    RecalculateAttendanceRangeUseCase,
    SubmitOvertimeApplicationInput,
    SubmitOvertimeApplicationUseCase,
    UpdateOvertimeApplicationInput,
    UpdateOvertimeApplicationUseCase,
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
from app.attendance.infrastructure.overtime_router import (
    submit_overtime_application,
    update_overtime_application,
)
from app.attendance.infrastructure.overtime_schemas import (
    AttendanceRangeRecalculationInputSchema,
    AttendanceRangeRecalculationSchema,
    OvertimeApplicationInputSchema,
)
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
        self.saved_attendances = []
        self.employee_user_id = uuid4()
        self.schedule_break_rules = []

    async def get_active_employee_id_for_user(self, user_id):
        return self.employee.id

    async def get_user_id_for_employee(self, employee_id):
        return self.employee_user_id

    async def get_current_cutoff(self, employee_id, today):
        return self.cutoff

    async def get_cutoff_for_employee_on_date(self, employee_id, work_date):
        return self.cutoff

    async def list_completed_attendance_in_period(self, user_id, period_start, period_end):
        self.period = (period_start, period_end)
        return [self.attendance] * 7

    async def list_employee_attendance_in_range(
        self, employee_id, from_date, to_date, *, lock_for_update=False,
    ):
        self.range = (employee_id, from_date, to_date, lock_for_update)
        records = getattr(self, "range_attendance", [self.attendance])
        return [
            record for record in records
            if record is not None and from_date <= record.work_date <= to_date
        ]

    async def list_break_rules_for_template(self, schedule_template_id):
        self.break_rule_template_id = schedule_template_id
        return self.schedule_break_rules

    async def lock_completed_attendance(self, attendance_id, user_id):
        return (self.attendance, self.employee) if self.attendance is not None else None

    async def lock_owned_application(self, application_id, user_id):
        application = next((item for item in self.applications if item.id == application_id), None)
        if application is None:
            return None
        return OvertimeApplicationRecord(application, self.attendance, self.employee)

    async def has_open_application(self, attendance_id, overtime_type=None, exclude_application_id=None):
        return any(
            app.status in rules.OPEN_APPLICATION_STATUSES
            and (overtime_type is None or app.overtime_type == overtime_type)
            and app.id != exclude_application_id
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
        self.saved_attendances.append(attendance)

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

    async def test_submission_after_employee_review_deadline_is_rejected(self):
        self.cutoff.employee_review_deadline = NOW - timedelta(seconds=1)
        with self.assertRaisesRegex(ConflictError, "employee filing deadline"):
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


class UpdateOvertimeApplicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id = uuid4()
        self.attendance = make_attendance(night_differential_overtime_minutes=90)
        self.employee = make_employee()
        self.cutoff = OvertimeCutoff("OCT-1", date(2026, 10, 1), date(2026, 10, 15))
        self.application = OvertimeApplication(
            id=uuid4(), application_no="OT-EDIT", employee_id=self.employee.id,
            attendance_record_id=self.attendance.id, attendance_date=self.attendance.work_date,
            requested_start_at=datetime(2026, 10, 12, 9, tzinfo=timezone.utc),
            requested_end_at=datetime(2026, 10, 12, 10, tzinfo=timezone.utc),
            potential_ot_minutes=120, requested_minutes=60,
            overtime_type="REGULAR_OVERTIME", reason="Original reason", status="PENDING",
        )
        self.repository = FakeOvertimeRepository(self.attendance, self.employee, self.cutoff)
        self.repository.applications = [self.application]
        self.uow = FakeUnitOfWork(self.repository)
        self.refresher = MagicMock()
        self.audit = MagicMock(record=AsyncMock())
        self.use_case = UpdateOvertimeApplicationUseCase(
            self.uow, self.refresher, self.audit, clock=lambda: NOW,
        )

    async def update(self, **changes):
        values = dict(
            user_id=self.user_id, application_id=self.application.id,
            overtime_type="NIGHT_DIFFERENTIAL_OVERTIME", requested_minutes=45,
            requested_start_at=datetime(2026, 10, 12, 9, tzinfo=timezone.utc),
            requested_end_at=datetime(2026, 10, 12, 9, 45, tzinfo=timezone.utc),
            reason="Corrected request", work_accomplished="Completed handover",
        )
        values.update(changes)
        return await self.use_case.execute(UpdateOvertimeApplicationInput(**values))

    async def test_pending_application_can_be_edited_and_saved_for_review(self):
        record = await self.update()
        self.assertEqual(record.application.overtime_type, "NIGHT_DIFFERENTIAL_OVERTIME")
        self.assertEqual(record.application.requested_minutes, 45)
        self.assertEqual(record.application.reason, "Corrected request")
        self.assertEqual(record.application.work_accomplished, "Completed handover")
        self.assertEqual(record.application.status, "PENDING")
        self.assertIs(self.repository.saved_attendance, self.attendance)
        self.assertEqual(self.attendance.requested_night_differential_overtime_minutes, 45)
        self.refresher.request_refresh.assert_called_once_with(self.user_id)
        self.audit.record.assert_awaited_once()
        self.assertEqual(self.audit.record.await_args.kwargs["action"], "UPDATE")

    async def test_editing_rejected_application_resubmits_it_as_pending(self):
        self.application.status = "REJECTED"
        self.application.supervisor_approved_minutes = 0
        self.application.final_payable_minutes = 0
        await self.update()
        self.assertEqual(self.application.status, "PENDING")
        self.assertIsNone(self.application.supervisor_approved_minutes)
        self.assertIsNone(self.application.final_payable_minutes)

    async def test_approved_application_cannot_be_edited(self):
        self.application.status = "APPROVED"
        with self.assertRaisesRegex(ConflictError, "cannot be edited"):
            await self.update()
        self.assertEqual(self.application.reason, "Original reason")
        self.refresher.request_refresh.assert_not_called()
        self.audit.record.assert_not_awaited()

    async def test_edit_cannot_duplicate_another_open_application_type(self):
        duplicate = OvertimeApplication(
            id=uuid4(), application_no="OT-OTHER", employee_id=self.employee.id,
            attendance_record_id=self.attendance.id, attendance_date=self.attendance.work_date,
            requested_start_at=NOW, requested_end_at=NOW + timedelta(minutes=30),
            potential_ot_minutes=90, requested_minutes=30,
            overtime_type="NIGHT_DIFFERENTIAL_OVERTIME", reason="Other", status="PENDING",
        )
        self.repository.applications.append(duplicate)
        with self.assertRaisesRegex(ConflictError, "already has a pending or approved"):
            await self.update()
        self.assertEqual(self.application.overtime_type, "REGULAR_OVERTIME")

    async def test_http_router_translates_domain_errors(self):
        payload = OvertimeApplicationInputSchema(
            overtime_type="REGULAR_OVERTIME", requested_minutes=30, reason="Update request",
        )
        use_case = MagicMock(execute=AsyncMock(side_effect=ConflictError("approved")))
        with self.assertRaises(HTTPException) as raised:
            await update_overtime_application(
                self.application.id, payload,
                claims={"sub": str(self.user_id)}, use_case=use_case,
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "approved")


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
    def use_case(self, repository):
        return GetOvertimeAttendanceOptionsUseCase(
            FakeUnitOfWork(repository),
            MagicMock(),
            MagicMock(record=AsyncMock()),
            clock=lambda: NOW,
        )

    async def test_options_return_every_record_in_the_current_cutoff(self):
        cutoff = OvertimeCutoff("OCT-1", date(2026, 10, 1), date(2026, 10, 15))
        repository = FakeOvertimeRepository(make_attendance(), cutoff=cutoff)
        use_case = self.use_case(repository)

        options = await use_case.execute(GetOvertimeAttendanceOptionsInput(user_id=uuid4()))

        self.assertEqual(len(options.attendance), 7)
        self.assertEqual(options.cutoff.cutoff_code, "OCT-1")
        self.assertEqual(repository.period, (cutoff.period_start, cutoff.period_end))

    async def test_options_recalculate_legacy_after_midnight_overtime_split(self):
        ph_timezone = timezone(timedelta(hours=8))
        attendance = make_attendance(
            expected_clock_in_at=datetime(2026, 10, 8, 17, tzinfo=ph_timezone),
            expected_clock_out_at=datetime(2026, 10, 9, 2, tzinfo=ph_timezone),
            clock_in_at=datetime(2026, 10, 8, 17, tzinfo=ph_timezone),
            clock_out_at=datetime(2026, 10, 9, 9, tzinfo=ph_timezone),
            corrected_clock_in_at=None,
            corrected_clock_out_at=None,
            regular_overtime_minutes=7 * 60,
            night_differential_overtime_minutes=0,
            punch_metadata={
                "schedule_context": {
                    "ot_eligible": True,
                    "minimum_ot_minutes": 0,
                    "pre_shift_ot_allowed": False,
                    "break_rules": [],
                }
            },
        )
        repository = FakeOvertimeRepository(
            attendance,
            cutoff=OvertimeCutoff("OCT-1", date(2026, 10, 1), date(2026, 10, 15)),
        )
        repository.list_completed_attendance_in_period = AsyncMock(return_value=[attendance])
        refresher = MagicMock()
        audit = MagicMock(record=AsyncMock())
        use_case = GetOvertimeAttendanceOptionsUseCase(
            FakeUnitOfWork(repository), refresher, audit, clock=lambda: NOW,
        )

        options = await use_case.execute(
            GetOvertimeAttendanceOptionsInput(user_id=attendance.user_id),
        )

        self.assertEqual(
            (
                options.attendance[0].regular_overtime_minutes,
                options.attendance[0].night_differential_overtime_minutes,
                options.attendance[0].calculated_ot_minutes,
            ),
            (3 * 60, 4 * 60, 7 * 60),
        )
        self.assertIs(repository.saved_attendance, attendance)
        refresher.request_refresh.assert_called_once_with(attendance.user_id)
        audit.record.assert_awaited_once()
        self.assertEqual(audit.record.await_args.kwargs["action"], "RECALCULATE")

    async def test_missing_cutoff_is_reported_instead_of_listing_old_attendance(self):
        repository = FakeOvertimeRepository(make_attendance(), cutoff=None)
        use_case = self.use_case(repository)
        with self.assertRaisesRegex(RuleViolationError, "Contact HR"):
            await use_case.execute(GetOvertimeAttendanceOptionsInput(user_id=uuid4()))


class AttendanceRangeRecalculationTests(unittest.IsolatedAsyncioTestCase):
    def test_request_defaults_to_dry_run_and_validates_inclusive_date_range(self):
        employee_id = uuid4()
        payload = AttendanceRangeRecalculationInputSchema(
            employee_id=employee_id,
            from_date=date(2026, 10, 8),
            to_date=date(2026, 10, 9),
        )

        self.assertTrue(payload.dry_run)
        with self.assertRaises(ValidationError):
            AttendanceRangeRecalculationInputSchema(
                employee_id=employee_id,
                from_date=date(2026, 10, 10),
                to_date=date(2026, 10, 9),
            )

    async def test_dry_run_preserves_schedule_boundaries_and_recalculates_ot_nd_without_saving(self):
        ph_timezone = timezone(timedelta(hours=8))
        schedule_context = {
            "ot_eligible": True,
            "minimum_ot_minutes": 0,
            "pre_shift_ot_allowed": False,
            "break_rules": [],
        }
        night_overtime_record = make_attendance(
            work_date=date(2026, 10, 8),
            expected_clock_in_at=datetime(2026, 10, 8, 17, tzinfo=ph_timezone),
            expected_clock_out_at=datetime(2026, 10, 9, 2, tzinfo=ph_timezone),
            clock_in_at=datetime(2026, 10, 8, 17, tzinfo=ph_timezone),
            clock_out_at=datetime(2026, 10, 9, 9, tzinfo=ph_timezone),
            corrected_clock_in_at=None,
            corrected_clock_out_at=None,
            regular_overtime_minutes=0,
            night_differential_overtime_minutes=0,
            punch_metadata={"schedule_context": schedule_context},
        )
        shifted_record = make_attendance(
            work_date=date(2026, 10, 8),
            expected_clock_in_at=datetime(2026, 10, 8, 17, tzinfo=ph_timezone),
            expected_clock_out_at=datetime(2026, 10, 9, 2, tzinfo=ph_timezone),
            clock_in_at=datetime(2026, 10, 8, 17, 15, tzinfo=ph_timezone),
            clock_out_at=datetime(2026, 10, 9, 9, 15, tzinfo=ph_timezone),
            corrected_clock_in_at=None,
            corrected_clock_out_at=None,
            punch_metadata={"schedule_context": schedule_context},
        )
        repository = FakeOvertimeRepository(night_overtime_record)
        repository.range_attendance = [night_overtime_record, shifted_record]
        refresher = MagicMock()
        audit = MagicMock(record=AsyncMock())
        use_case = RecalculateAttendanceRangeUseCase(
            FakeUnitOfWork(repository), refresher, audit, clock=lambda: NOW,
        )

        result = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 8),
                to_date=date(2026, 10, 8),
            )
        )

        self.assertEqual(repository.range[1:], (date(2026, 10, 8), date(2026, 10, 8), False))
        self.assertTrue(result.dry_run)
        self.assertEqual(result.preview_count, 2)
        self.assertEqual(result.records[0].regular_overtime_minutes, 180)
        self.assertEqual(result.records[0].night_differential_overtime_minutes, 240)
        self.assertEqual(result.records[0].night_differential_minutes, 480)
        self.assertEqual(result.records[0].regular_night_differential_minutes, 240)
        self.assertEqual(result.records[0].previous_late_minutes, 0)
        self.assertEqual(result.records[0].late_minutes, 0)
        self.assertEqual(result.records[1].previous_late_minutes, 0)
        self.assertEqual(result.records[1].late_minutes, 15)
        self.assertEqual(
            result.records[1].actual_clock_in_at,
            datetime(2026, 10, 8, 17, 15, tzinfo=ph_timezone),
        )
        self.assertEqual(
            result.records[1].expected_clock_in_at,
            datetime(2026, 10, 8, 17, tzinfo=ph_timezone),
        )
        self.assertEqual(
            result.records[1].expected_clock_out_at,
            datetime(2026, 10, 9, 2, tzinfo=ph_timezone),
        )
        self.assertEqual(result.records[1].regular_overtime_minutes, 195)
        self.assertEqual(result.records[1].night_differential_overtime_minutes, 240)
        self.assertEqual(result.records[1].regular_night_differential_minutes, 240)
        self.assertEqual(result.records[1].calculated_ot_minutes, 435)
        self.assertEqual(repository.saved_attendances, [])
        refresher.request_refresh.assert_not_called()
        audit.record.assert_not_awaited()
        response = AttendanceRangeRecalculationSchema.model_validate(result)
        self.assertEqual(response.preview_count, 2)
        self.assertEqual(response.records[0].regular_night_differential_minutes, 240)

    async def test_apply_persists_changes_and_audits_them(self):
        ph_timezone = timezone(timedelta(hours=8))
        attendance = make_attendance(
            work_date=date(2026, 10, 8),
            expected_clock_in_at=datetime(2026, 10, 8, 17, tzinfo=ph_timezone),
            expected_clock_out_at=datetime(2026, 10, 9, 2, tzinfo=ph_timezone),
            clock_in_at=datetime(2026, 10, 8, 17, 15, tzinfo=ph_timezone),
            clock_out_at=datetime(2026, 10, 9, 9, 15, tzinfo=ph_timezone),
            corrected_clock_in_at=None,
            corrected_clock_out_at=None,
            punch_metadata={
                "schedule_context": {
                    "ot_eligible": True,
                    "minimum_ot_minutes": 0,
                    "pre_shift_ot_allowed": False,
                    "break_rules": [],
                }
            },
        )
        repository = FakeOvertimeRepository(attendance)
        refresher = MagicMock()
        audit = MagicMock(record=AsyncMock())
        use_case = RecalculateAttendanceRangeUseCase(
            FakeUnitOfWork(repository), refresher, audit, clock=lambda: NOW,
        )

        result = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 8),
                to_date=date(2026, 10, 8),
                dry_run=False,
            )
        )

        self.assertEqual(result.updated_count, 1)
        self.assertTrue(repository.range[3])
        self.assertIs(repository.saved_attendance, attendance)
        self.assertEqual(attendance.regular_overtime_minutes, 195)
        self.assertEqual(attendance.night_differential_overtime_minutes, 240)
        self.assertEqual(attendance.late_minutes, 15)
        self.assertEqual(attendance.expected_clock_in_at, datetime(2026, 10, 8, 17, tzinfo=ph_timezone))
        self.assertEqual(attendance.expected_clock_out_at, datetime(2026, 10, 9, 2, tzinfo=ph_timezone))
        self.assertEqual(
            attendance.punch_metadata["recalculation_baseline_expected_clock_in_at"],
            datetime(2026, 10, 8, 17, tzinfo=ph_timezone).isoformat(),
        )
        self.assertEqual(
            attendance.punch_metadata["recalculation_baseline_expected_clock_out_at"],
            datetime(2026, 10, 9, 2, tzinfo=ph_timezone).isoformat(),
        )
        refresher.request_refresh.assert_called_once_with(attendance.user_id)
        audit.record.assert_awaited_once()

        preview = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 8),
                to_date=date(2026, 10, 8),
            )
        )
        self.assertEqual(preview.records[0].previous_late_minutes, 15)
        self.assertEqual(preview.records[0].late_minutes, 15)

    async def test_recalculation_repairs_prior_shifted_boundaries_from_saved_schedule_baseline(self):
        ph_timezone = timezone(timedelta(hours=8))
        attendance = make_attendance(
            work_date=date(2026, 10, 15),
            expected_clock_in_at=datetime(2026, 10, 15, 8, 17, tzinfo=ph_timezone),
            expected_clock_out_at=datetime(2026, 10, 15, 17, 17, tzinfo=ph_timezone),
            clock_in_at=datetime(2026, 10, 15, 8, 17, tzinfo=ph_timezone),
            clock_out_at=datetime(2026, 10, 15, 17, tzinfo=ph_timezone),
            corrected_clock_in_at=None,
            corrected_clock_out_at=None,
            late_minutes=17,
            undertime_minutes=17,
            punch_metadata={
                "recalculation_baseline_expected_clock_in_at": (
                    datetime(2026, 10, 15, 8, tzinfo=ph_timezone).isoformat()
                ),
                "schedule_context": {
                    "grace_minutes": 15,
                    "ot_eligible": True,
                    "minimum_ot_minutes": 0,
                    "pre_shift_ot_allowed": False,
                    "break_rules": [],
                },
            },
        )
        repository = FakeOvertimeRepository(attendance)
        use_case = RecalculateAttendanceRangeUseCase(
            FakeUnitOfWork(repository), MagicMock(), MagicMock(record=AsyncMock()), clock=lambda: NOW,
        )

        result = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 15),
                to_date=date(2026, 10, 15),
            )
        )

        recalculated = result.records[0]
        self.assertEqual(recalculated.status, "PREVIEW")
        self.assertEqual(recalculated.expected_clock_in_at, datetime(2026, 10, 15, 8, tzinfo=ph_timezone))
        self.assertEqual(recalculated.expected_clock_out_at, datetime(2026, 10, 15, 17, tzinfo=ph_timezone))
        self.assertEqual(recalculated.late_minutes, 2)
        self.assertEqual(recalculated.undertime_minutes, 0)

        applied = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 15),
                to_date=date(2026, 10, 15),
                dry_run=False,
            )
        )
        self.assertEqual(applied.updated_count, 1)
        self.assertIs(repository.saved_attendance, attendance)
        self.assertEqual(attendance.expected_clock_in_at, datetime(2026, 10, 15, 8, tzinfo=ph_timezone))
        self.assertEqual(attendance.expected_clock_out_at, datetime(2026, 10, 15, 17, tzinfo=ph_timezone))
        self.assertEqual(attendance.late_minutes, 2)
        self.assertEqual(attendance.undertime_minutes, 0)

    async def test_recalculation_deducts_first_break_excess_and_meal_break_from_worked_time(self):
        ph_timezone = timezone(timedelta(hours=8))
        scheduled_start = datetime(2026, 10, 15, 8, tzinfo=ph_timezone)
        scheduled_end = datetime(2026, 10, 15, 17, tzinfo=ph_timezone)
        attendance = make_attendance(
            work_date=date(2026, 10, 15),
            expected_clock_in_at=scheduled_start,
            expected_clock_out_at=scheduled_end,
            clock_in_at=scheduled_start,
            clock_out_at=scheduled_end,
            first_break_out_at=datetime(2026, 10, 15, 12, tzinfo=ph_timezone),
            first_break_in_at=datetime(2026, 10, 15, 12, 20, tzinfo=ph_timezone),
            meal_break_out_at=datetime(2026, 10, 15, 13, tzinfo=ph_timezone),
            meal_break_in_at=datetime(2026, 10, 15, 14, 15, tzinfo=ph_timezone),
            corrected_clock_in_at=None,
            corrected_clock_out_at=None,
            punch_metadata={
                "schedule_context": {
                    "ot_eligible": True,
                    "minimum_ot_minutes": 0,
                    "pre_shift_ot_allowed": False,
                    "break_rules": [
                        {
                            "break_slot": "FIRST_BREAK",
                            "segment_type": "PAID_BREAK",
                            "break_minutes": 15,
                            "auto_deduct": False,
                        },
                        {
                            "break_slot": "MEAL_BREAK",
                            "segment_type": "UNPAID_BREAK",
                            "break_minutes": 60,
                            "auto_deduct": False,
                        },
                    ],
                }
            },
        )
        repository = FakeOvertimeRepository(attendance)
        use_case = RecalculateAttendanceRangeUseCase(
            FakeUnitOfWork(repository), MagicMock(), MagicMock(record=AsyncMock()), clock=lambda: NOW,
        )

        result = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 15),
                to_date=date(2026, 10, 15),
            )
        )

        self.assertEqual(result.records[0].undertime_minutes, 0)
        self.assertEqual(result.records[0].excess_minutes_break, 20)
        self.assertEqual(result.records[0].minutes_worked, 460)

        applied = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 15),
                to_date=date(2026, 10, 15),
                dry_run=False,
            )
        )
        self.assertEqual(applied.updated_count, 1)
        self.assertEqual(
            attendance.punch_metadata["break_calculation"]["excess_minutes_break"],
            20,
        )
        self.assertTrue(
            attendance.punch_metadata["break_calculation"]["undertime_excludes_break_excess"],
        )
        self.assertEqual(
            attendance.punch_metadata["break_calculation"]["unpaid_break_minutes"],
            75,
        )
        self.assertEqual(
            attendance.punch_metadata["break_calculation"]["net_nonpayable_minutes"],
            80,
        )

    async def test_recalculation_applies_configured_paid_overtime_break_allowance(self):
        ph_timezone = timezone(timedelta(hours=8))
        scheduled_start = datetime(2026, 10, 15, 8, tzinfo=ph_timezone)
        scheduled_end = datetime(2026, 10, 15, 17, tzinfo=ph_timezone)
        attendance = make_attendance(
            work_date=date(2026, 10, 15),
            expected_clock_in_at=scheduled_start,
            expected_clock_out_at=scheduled_end,
            clock_in_at=scheduled_start,
            clock_out_at=datetime(2026, 10, 15, 19, 30, tzinfo=ph_timezone),
            meal_break_out_at=datetime(2026, 10, 15, 12, tzinfo=ph_timezone),
            meal_break_in_at=datetime(2026, 10, 15, 13, tzinfo=ph_timezone),
            ot_break_out_at=datetime(2026, 10, 15, 18, tzinfo=ph_timezone),
            ot_break_in_at=datetime(2026, 10, 15, 18, 20, tzinfo=ph_timezone),
            corrected_clock_in_at=None,
            corrected_clock_out_at=None,
            punch_metadata={
                "schedule_context": {
                    "ot_eligible": True,
                    "minimum_ot_minutes": 0,
                    "pre_shift_ot_allowed": False,
                    "break_rules": [
                        {
                            "break_slot": "MEAL_BREAK",
                            "segment_type": "UNPAID_BREAK",
                            "break_minutes": 60,
                            "auto_deduct": False,
                        },
                        {
                            "break_slot": "OT_BREAK",
                            "segment_type": "PAID_BREAK",
                            "break_minutes": 15,
                            "auto_deduct": False,
                        },
                    ],
                }
            },
        )
        repository = FakeOvertimeRepository(attendance)
        use_case = RecalculateAttendanceRangeUseCase(
            FakeUnitOfWork(repository), MagicMock(), MagicMock(record=AsyncMock()), clock=lambda: NOW,
        )

        result = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 15),
                to_date=date(2026, 10, 15),
            )
        )

        record = result.records[0]
        self.assertEqual(record.calculated_ot_minutes, 145)
        self.assertEqual(record.minutes_worked, 625)
        self.assertEqual(record.excess_minutes_break, 5)

        await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 15),
                to_date=date(2026, 10, 15),
                dry_run=False,
            )
        )
        break_calculation = attendance.punch_metadata["break_calculation"]
        self.assertEqual(break_calculation["unpaid_break_minutes"], 60)
        self.assertEqual(break_calculation["excess_minutes_break"], 5)
        self.assertEqual(break_calculation["net_nonpayable_minutes"], 65)

    async def test_recalculation_loads_template_break_rules_when_snapshot_is_missing(self):
        ph_timezone = timezone(timedelta(hours=8))
        template_id = uuid4()
        attendance = make_attendance(
            work_date=date(2026, 10, 15),
            expected_clock_in_at=datetime(2026, 10, 15, 8, tzinfo=ph_timezone),
            expected_clock_out_at=datetime(2026, 10, 15, 17, tzinfo=ph_timezone),
            clock_in_at=datetime(2026, 10, 15, 8, 17, tzinfo=ph_timezone),
            clock_out_at=datetime(2026, 10, 15, 19, 40, tzinfo=ph_timezone),
            first_break_out_at=datetime(2026, 10, 15, 10, 15, tzinfo=ph_timezone),
            first_break_in_at=datetime(2026, 10, 15, 10, 35, tzinfo=ph_timezone),
            corrected_clock_in_at=None,
            corrected_clock_out_at=None,
            punch_metadata={"schedule_context": {"ot_eligible": True}},
        )
        attendance.schedule_template_id = template_id
        repository = FakeOvertimeRepository(attendance)
        repository.schedule_break_rules = [
            {
                "break_slot": "FIRST_BREAK",
                "segment_type": "PAID_BREAK",
                "break_minutes": 10,
                "auto_deduct": False,
            },
        ]
        use_case = RecalculateAttendanceRangeUseCase(
            FakeUnitOfWork(repository), MagicMock(), MagicMock(record=AsyncMock()), clock=lambda: NOW,
        )

        result = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 15),
                to_date=date(2026, 10, 15),
            )
        )

        self.assertEqual(repository.break_rule_template_id, template_id)
        self.assertEqual(result.records[0].excess_minutes_break, 10)
        self.assertEqual(result.records[0].minutes_worked, 673)
        self.assertEqual(
            result.records[0].break_calculation_details[0].duration_minutes,
            20,
        )
        self.assertEqual(
            result.records[0].break_calculation_details[0].allowance_minutes,
            10,
        )
        self.assertEqual(
            result.records[0].break_calculation_details[0].excess_minutes,
            10,
        )
        response = AttendanceRangeRecalculationSchema.model_validate(result)
        self.assertEqual(
            response.records[0].break_calculation_details[0].duration_minutes,
            20,
        )
        self.assertEqual(
            response.records[0].break_calculation_details[0].allowance_minutes,
            10,
        )

    async def test_recalculation_fills_break_rules_missing_from_partial_snapshot(self):
        ph_timezone = timezone(timedelta(hours=8))
        template_id = uuid4()
        attendance = make_attendance(
            work_date=date(2026, 10, 15),
            expected_clock_in_at=datetime(2026, 10, 15, 8, tzinfo=ph_timezone),
            expected_clock_out_at=datetime(2026, 10, 15, 17, tzinfo=ph_timezone),
            clock_in_at=datetime(2026, 10, 15, 8, 17, tzinfo=ph_timezone),
            clock_out_at=datetime(2026, 10, 15, 19, 40, tzinfo=ph_timezone),
            first_break_out_at=datetime(2026, 10, 15, 10, 15, tzinfo=ph_timezone),
            first_break_in_at=datetime(2026, 10, 15, 10, 35, tzinfo=ph_timezone),
            corrected_clock_in_at=None,
            corrected_clock_out_at=None,
            punch_metadata={
                "schedule_context": {
                    "ot_eligible": True,
                    "break_rules": [
                        {
                            "break_slot": "MEAL_BREAK",
                            "segment_type": "UNPAID_BREAK",
                            "break_minutes": 60,
                            "auto_deduct": False,
                        },
                    ],
                },
            },
        )
        attendance.schedule_template_id = template_id
        repository = FakeOvertimeRepository(attendance)
        repository.schedule_break_rules = [
            {
                "break_slot": "FIRST_BREAK",
                "segment_type": "PAID_BREAK",
                "break_minutes": 10,
                "auto_deduct": False,
            },
        ]
        use_case = RecalculateAttendanceRangeUseCase(
            FakeUnitOfWork(repository), MagicMock(), MagicMock(record=AsyncMock()), clock=lambda: NOW,
        )

        result = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 15),
                to_date=date(2026, 10, 15),
            )
        )

        self.assertEqual(repository.break_rule_template_id, template_id)
        self.assertEqual(result.records[0].excess_minutes_break, 10)
        self.assertEqual(result.records[0].minutes_worked, 673)

    async def test_existing_overtime_applications_are_reported_and_not_changed(self):
        ph_timezone = timezone(timedelta(hours=8))
        attendance = make_attendance(
            work_date=date(2026, 10, 8),
            expected_clock_in_at=datetime(2026, 10, 8, 17, tzinfo=ph_timezone),
            expected_clock_out_at=datetime(2026, 10, 9, 2, tzinfo=ph_timezone),
            clock_in_at=datetime(2026, 10, 8, 17, tzinfo=ph_timezone),
            clock_out_at=datetime(2026, 10, 9, 9, tzinfo=ph_timezone),
            corrected_clock_in_at=None,
            corrected_clock_out_at=None,
            punch_metadata={
                "schedule_context": {
                    "ot_eligible": True,
                    "minimum_ot_minutes": 0,
                    "pre_shift_ot_allowed": False,
                    "break_rules": [],
                }
            },
        )
        repository = FakeOvertimeRepository(attendance)
        repository.applications = [
            OvertimeApplication(
                application_no="OT-1",
                employee_id=uuid4(),
                attendance_record_id=attendance.id,
                attendance_date=attendance.work_date,
                requested_start_at=datetime(2026, 10, 9, 2, tzinfo=ph_timezone),
                requested_end_at=datetime(2026, 10, 9, 3, tzinfo=ph_timezone),
                potential_ot_minutes=60,
                requested_minutes=60,
                overtime_type="REGULAR_OVERTIME",
                reason="Existing request",
            )
        ]
        use_case = RecalculateAttendanceRangeUseCase(
            FakeUnitOfWork(repository), MagicMock(), MagicMock(record=AsyncMock()),
            clock=lambda: NOW,
        )

        result = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 8),
                to_date=date(2026, 10, 8),
                dry_run=False,
            )
        )

        self.assertEqual(result.skipped_count, 1)
        self.assertIn("OT application", result.records[0].reason)
        self.assertEqual(repository.saved_attendances, [])

    async def test_attendance_with_incomplete_punches_is_reported_as_skipped(self):
        attendance = make_attendance(
            work_date=date(2026, 10, 8),
            clock_out_at=None,
            corrected_clock_out_at=None,
        )
        repository = FakeOvertimeRepository(attendance)
        use_case = RecalculateAttendanceRangeUseCase(
            FakeUnitOfWork(repository), MagicMock(), MagicMock(record=AsyncMock()),
            clock=lambda: NOW,
        )

        result = await use_case.execute(
            RecalculateAttendanceRangeInput(
                actor_user_id=uuid4(),
                employee_id=uuid4(),
                from_date=date(2026, 10, 8),
                to_date=date(2026, 10, 8),
            )
        )

        self.assertEqual(result.skipped_count, 1)
        self.assertIn("complete effective punches", result.records[0].reason)
        self.assertEqual(repository.saved_attendances, [])


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

    async def test_employee_date_range_query_locks_only_when_requested(self):
        init_db_models()
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=SimpleNamespace(all=lambda: [])))
        )

        await SqlAlchemyOvertimeRepository(session).list_employee_attendance_in_range(
            uuid4(), date(2026, 10, 1), date(2026, 10, 15), lock_for_update=True,
        )

        statement = str(session.execute.call_args.args[0])
        self.assertIn("work_date >=", statement)
        self.assertIn("work_date <=", statement)
        self.assertIn("employee_id =", statement)
        self.assertIn("FOR UPDATE", statement)


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
