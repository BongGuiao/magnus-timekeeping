import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text

from app.attendance.application.correction_calculation import recalculate_corrected_attendance
from app.attendance.application.correction_finalization import require_resolved_punches
from app.attendance.domain.entities.overtime import OvertimeAttendance
from app.attendance.infrastructure import correction_router as corrections
from app.attendance.infrastructure.correction_db_model import AttendanceCorrectionModel
from app.attendance.infrastructure.db_model import AttendanceModel
from app.core.database import AsyncSessionLocal, engine, init_db_models
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import EmployeeCutoffResultModel

MANILA = timezone(timedelta(hours=8))
WORK_DATE = date(2026, 10, 12)
START = datetime(2026, 10, 12, 9, tzinfo=MANILA)
END = datetime(2026, 10, 12, 18, tzinfo=MANILA)


def payload(**changes):
    values = dict(work_date=WORK_DATE, requested_clock_in_at=START, requested_clock_out_at=END, reason="Forgot clock-out")
    values.update(changes)
    return corrections.CorrectionCreate(**values)


def day(**changes):
    values = dict(
        id=uuid4(), user_id=uuid4(), work_date=WORK_DATE, expected_clock_in_at=START, expected_clock_out_at=END,
        punch_metadata={"schedule_context": {"ot_eligible": True, "grace_minutes": 5}},
    )
    values.update(changes)
    return OvertimeAttendance(**values)


class CorrectionValidationTests(unittest.TestCase):
    def test_requires_timezone_chronology_work_date_reason_and_no_ownership_fields(self):
        for changes in (
            {"requested_clock_in_at": START.replace(tzinfo=None)},
            {"requested_clock_out_at": START}, {"work_date": WORK_DATE + timedelta(days=1)},
            {"requested_clock_out_at": END + timedelta(days=2)}, {"reason": "   "}, {"employee_id": str(uuid4())},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                payload(**changes)

    def test_overnight_clock_out_is_allowed_on_next_day(self):
        payload(requested_clock_in_at=START.replace(hour=22),
                requested_clock_out_at=END.replace(hour=6) + timedelta(days=1))

    def test_cannot_change_present_punch_or_fill_already_completed_record(self):
        for record in (day(clock_in_at=START), day(clock_in_at=START, clock_out_at=END)):
            with self.assertRaises(HTTPException):
                corrections._validate_missing(record, payload(requested_clock_in_at=START + timedelta(minutes=1)))
        corrections._validate_missing(day(clock_in_at=START), payload())

    def test_breaks_must_fit_requested_working_period(self):
        with self.assertRaisesRegex(HTTPException, ""):
            corrections._validate_missing(day(clock_in_at=START, first_break_out_at=START - timedelta(minutes=1)), payload())

    def test_both_missing_punches_rejected(self):
        with self.assertRaises(HTTPException) as error:
            corrections._validate_missing(day(), payload())
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("At least one existing", error.exception.detail)

    def test_recalculation_keeps_ot_separate_and_uses_schedule_metrics(self):
        values = recalculate_corrected_attendance(day(), START + timedelta(minutes=30), END + timedelta(hours=2))
        self.assertEqual(values["late_minutes"], 25)
        self.assertEqual(values["regular_overtime_minutes"], 120)
        self.assertNotIn("approved_regular_overtime_minutes", values)
        self.assertNotIn("approved_ot_worked", values)
        self.assertNotIn("clock_in_at", values)
        self.assertNotIn("clock_out_at", values)

    def test_missing_saved_schedule_is_explicit_error(self):
        with self.assertRaisesRegex(ValueError, "schedule policy"):
            recalculate_corrected_attendance(day(punch_metadata={}), START, END)

    def test_overnight_correction_recalculates_night_differential(self):
        start = START.replace(hour=22)
        end = END.replace(hour=6) + timedelta(days=1)
        values = recalculate_corrected_attendance(
            day(expected_clock_in_at=start, expected_clock_out_at=end), start, end,
        )
        self.assertEqual(values["night_differential_minutes"], 480)
        self.assertEqual(values["calculated_ot_minutes"], 0)

    def test_rejection_and_approval_require_notes_and_version(self):
        for decision in ("APPROVED", "REJECTED"):
            with self.assertRaises(ValidationError):
                corrections.CorrectionDecision(decision=decision, row_version=1, review_notes=" ")
        with self.assertRaises(ValidationError):
            corrections.CorrectionDecision(decision="APPROVED", row_version=0, review_notes="Verified")


class CorrectionFinalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_filing_and_approval_are_separate_and_cutoffs_are_locked(self):
        now = datetime.now(timezone.utc)
        cutoff = SimpleNamespace(
            id=uuid4(), cutoff_code="TEST", period_start=WORK_DATE, period_end=WORK_DATE,
            employee_filing_deadline=now - timedelta(minutes=1), attendance_deadline=now + timedelta(days=1),
            attendance_finalized_at=None, locked_at=None, status="SCHEDULED",
        )
        assignment = SimpleNamespace(effective_from=WORK_DATE, effective_to=None, separation_date=None)
        session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(cutoff, assignment)])))
        with self.assertRaises(HTTPException) as filing:
            await corrections._open(session, uuid4(), WORK_DATE, "FILING")
        self.assertEqual(filing.exception.status_code, 409)
        self.assertEqual(await corrections._open(session, uuid4(), WORK_DATE, "APPROVAL"), [cutoff])
        self.assertTrue(session.execute.await_args.args[0]._for_update_arg is not None)
        cutoff.attendance_finalized_at = now
        with self.assertRaises(HTTPException):
            await corrections._open(session, uuid4(), WORK_DATE, "APPROVAL")

    async def test_pending_or_incomplete_attendance_blocks_finalization(self):
        cutoff = SimpleNamespace(payroll_group_id=uuid4(), period_start=WORK_DATE, period_end=WORK_DATE)
        for counts, message in (([1], "pending"), ([0, 1], "incomplete")):
            session = SimpleNamespace(scalar=AsyncMock(side_effect=counts))
            with self.assertRaisesRegex(ValueError, message):
                await require_resolved_punches(session, cutoff)
        session = SimpleNamespace(scalar=AsyncMock(side_effect=[0, 0]))
        await require_resolved_punches(session, cutoff)
        self.assertIn("corrected_clock_out_at", str(session.scalar.await_args.args[0]))
        self.assertIn("SCHEDULE_CREDITED", str(session.scalar.await_args.args[0].compile(compile_kwargs={"literal_binds": True})))


class TransactionUnitOfWork:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class CorrectionDatabaseTests(unittest.IsolatedAsyncioTestCase):
    """Exercises real persistence; schema and fixture changes are always rolled back."""

    async def asyncSetUp(self):
        init_db_models()
        self.patches = []
        self.session = AsyncSessionLocal()
        self.addAsyncCleanup(self.cleanup)
        await self.session.begin()
        connection = await self.session.connection()
        raw = await connection.get_raw_connection()
        script = Path("sql/20261101_attendance_correction_requests.sql").read_text().replace("BEGIN;", "").replace("COMMIT;", "")
        await raw.driver_connection.execute("SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='20s';")
        await raw.driver_connection.execute(script)
        await raw.driver_connection.execute(script)
        pair = (await self.session.execute(text("""
            SELECT employee_user.id AS user_id, employee_user.employee_id, supervisor_user.id AS reviewer_id,
                   a.payroll_group_id
            FROM hr.employment_assignments a
            JOIN identity.users employee_user ON employee_user.employee_id=a.employee_id
            JOIN identity.users supervisor_user ON supervisor_user.employee_id=a.supervisor_employee_id
            WHERE a.is_active AND a.status='ACTIVE' AND a.effective_from <= current_date
              AND (a.effective_to IS NULL OR a.effective_to >= current_date)
              AND (a.separation_date IS NULL OR a.separation_date >= current_date)
              AND a.employee_id <> a.supervisor_employee_id AND a.payroll_group_id IS NOT NULL
            LIMIT 1
        """))).first()
        if pair is None:
            self.skipTest("Integration database needs an employee and current supervisor with linked accounts.")
        self.user_id, self.employee_id, self.reviewer_id, payroll_group_id = pair
        self.cutoff = PayrollCutoffModel(
            id=uuid4(), payroll_group_id=payroll_group_id, cutoff_code=f"CORRECTION-TEST-{uuid4().hex[:8]}",
            period_start=WORK_DATE, period_end=WORK_DATE, pay_date=WORK_DATE,
            attendance_deadline=datetime.now(timezone.utc) + timedelta(days=1), calculation_version="TIME_TOTALS_V1",
        )
        self.session.add(self.cutoff)
        await self.session.flush()
        self.uow = TransactionUnitOfWork(self.session)
        self.patches = [
            patch.object(corrections, "_open", new=AsyncMock(return_value=[self.cutoff])),
            patch.object(corrections, "log_entity_action", new=AsyncMock()),
            patch.object(corrections, "queue_recent_attendance_refresh"),
        ]
        # A distinct account/date fixture avoids editing existing employee punches.
        self.work_date = (await self.session.execute(text("""
            SELECT d::date FROM generate_series(date '2026-10-01', date '2026-10-30', interval '1 day') d
            WHERE NOT EXISTS (
                SELECT 1 FROM attendance.attendance_records r WHERE r.user_id=:user AND r.work_date=d::date
            ) AND NOT EXISTS (
                SELECT 1 FROM attendance.correction_requests c WHERE c.employee_id=:employee AND c.work_date=d::date
            ) LIMIT 1
        """), {"user": self.user_id, "employee": self.employee_id})).scalar_one()
        self.start = datetime.combine(self.work_date, START.timetz())
        self.end = datetime.combine(self.work_date, END.timetz())
        self.cutoff.period_start = self.work_date
        self.cutoff.period_end = self.work_date
        for item in self.patches:
            item.start()

    async def cleanup(self):
        for item in reversed(getattr(self, "patches", [])):
            item.stop()
        await self.session.rollback()
        await self.session.close()
        await engine.dispose()

    async def create(self):
        response = await corrections.create_correction(
            payload(work_date=self.work_date, requested_clock_in_at=self.start, requested_clock_out_at=self.end),
            claims={"sub": str(self.user_id)}, uow=self.uow, es_client=None,
        )
        return response.data

    async def seed_incomplete(self):
        record = AttendanceModel(
            user_id=self.user_id, work_date=self.work_date, clock_in_at=self.start,
            expected_clock_in_at=self.start, expected_clock_out_at=self.end,
            punch_metadata={"schedule_context": {"ot_eligible": True}},
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def decide(self, request, decision="APPROVED", reviewer=None):
        return await corrections.decide_correction(
            request.id, corrections.CorrectionDecision(decision=decision, row_version=request.row_version, review_notes="Verified with employee"),
            claims={"sub": str(reviewer or self.reviewer_id)}, uow=self.uow, es_client=None,
        )

    async def test_no_attendance_or_both_missing_punches_cannot_be_filed(self):
        with self.assertRaises(HTTPException) as missing_record:
            await self.create()
        self.assertEqual(missing_record.exception.status_code, 409)
        record = await self.seed_incomplete()
        record.clock_in_at = None
        await self.session.flush()
        with self.assertRaises(HTTPException) as no_punches:
            await self.create()
        self.assertIn("At least one existing", no_punches.exception.detail)
        with self.assertRaises(HTTPException):
            await corrections.correction_day(
                work_date=self.work_date, claims={"sub": str(self.user_id)}, uow=self.uow,
            )
        self.assertIsNone(await self.session.scalar(select(AttendanceCorrectionModel.id).where(
            AttendanceCorrectionModel.employee_id == self.employee_id,
            AttendanceCorrectionModel.work_date == self.work_date,
        )))

    async def test_legacy_both_missing_request_cannot_be_approved_but_can_be_rejected(self):
        request = AttendanceCorrectionModel(
            employee_id=self.employee_id, user_id=self.user_id, work_date=self.work_date,
            requested_clock_in_at=self.start, requested_clock_out_at=self.end, reason="Legacy request",
        )
        self.session.add(request)
        await self.session.flush()
        await self.session.refresh(request)
        employee = await self.session.get(corrections.EmployeeModel, self.employee_id)
        output = corrections._output(request, employee)
        with self.assertRaises(HTTPException) as missing:
            await self.decide(output)
        self.assertEqual(missing.exception.status_code, 409)
        record = await self.seed_incomplete()
        record.clock_in_at = None
        await self.session.flush()
        with self.assertRaises(HTTPException) as no_punches:
            await self.decide(output)
        self.assertIn("At least one existing", no_punches.exception.detail)
        self.assertIsNone(record.corrected_clock_in_at)
        self.assertIsNone(record.corrected_clock_out_at)
        self.assertEqual((await self.decide(output, "REJECTED")).data.status, "REJECTED")

    async def test_existing_clock_in_is_preserved_and_cutoff_results_invalidated(self):
        record = AttendanceModel(
            user_id=self.user_id, work_date=self.work_date, clock_in_at=self.start,
            expected_clock_in_at=self.start, expected_clock_out_at=self.end,
            punch_metadata={"schedule_context": {"ot_eligible": True}},
        )
        self.session.add(record)
        self.session.add(EmployeeCutoffResultModel(
            cutoff_id=self.cutoff.id, employee_id=self.employee_id, calculated_at=datetime.now(timezone.utc),
            payroll_status="READY",
        ))
        await self.session.flush()
        request = await self.create()
        await self.decide(request)
        self.assertEqual(record.clock_in_at, self.start)
        self.assertIsNone(record.clock_out_at)
        self.assertIsNone(record.corrected_clock_in_at)
        self.assertEqual(record.corrected_clock_out_at, self.end)
        result = await self.session.scalar(select(EmployeeCutoffResultModel).where(EmployeeCutoffResultModel.cutoff_id == self.cutoff.id))
        self.assertEqual(result.payroll_status, "HOLD")
        self.assertIsNone(self.cutoff.calculation_version)

    async def test_existing_clock_out_is_preserved_when_clock_in_is_missing(self):
        record = AttendanceModel(
            user_id=self.user_id, work_date=self.work_date, clock_out_at=self.end,
            expected_clock_in_at=self.start, expected_clock_out_at=self.end,
            punch_metadata={"schedule_context": {"ot_eligible": True}},
        )
        self.session.add(record)
        await self.session.flush()
        await self.decide(await self.create())
        self.assertEqual(record.clock_out_at, self.end)
        self.assertIsNone(record.corrected_clock_out_at)
        self.assertIsNone(record.clock_in_at)
        self.assertEqual(record.corrected_clock_in_at, self.start)

    async def test_rejection_does_not_create_attendance_and_allows_refiling(self):
        record = await self.seed_incomplete()
        request = await self.create()
        self.assertEqual((await self.decide(request, "REJECTED")).data.status, "REJECTED")
        self.assertEqual(record.clock_in_at, self.start)
        self.assertIsNone(record.corrected_clock_out_at)
        self.assertEqual((await self.create()).status, "PENDING")
        self.assertEqual(self.cutoff.calculation_version, "TIME_TOTALS_V1")

    async def test_history_and_supervisor_pending_list_are_scoped(self):
        await self.seed_incomplete()
        request = await self.create()
        own = await corrections.list_corrections(claims={"sub": str(self.user_id)}, uow=self.uow)
        team = await corrections.pending_corrections(claims={"sub": str(self.reviewer_id)}, uow=self.uow)
        self.assertIn(request.id, [item.id for item in own.data])
        self.assertIn(request.id, [item.id for item in team.data])
        supervisor_history = await corrections.list_corrections(claims={"sub": str(self.reviewer_id)}, uow=self.uow)
        self.assertNotIn(request.id, [item.id for item in supervisor_history.data])
        await self.decide(request, "REJECTED")
        team = await corrections.pending_corrections(claims={"sub": str(self.reviewer_id)}, uow=self.uow)
        self.assertNotIn(request.id, [item.id for item in team.data])

    async def test_finalization_detects_pending_and_missing_punches_in_database(self):
        record = await self.seed_incomplete()
        request = await self.create()
        with self.assertRaisesRegex(ValueError, "pending"):
            await require_resolved_punches(self.session, self.cutoff)
        await self.decide(request, "REJECTED")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            await require_resolved_punches(self.session, self.cutoff)
        record.corrected_clock_out_at = self.end
        await self.session.flush()
        await require_resolved_punches(self.session, self.cutoff)

    async def test_self_approval_is_denied_and_changed_punches_cannot_be_overwritten(self):
        record = await self.seed_incomplete()
        request = await self.create()
        with self.assertRaises(HTTPException) as own:
            await self.decide(request, reviewer=self.user_id)
        self.assertEqual(own.exception.status_code, 404)
        record.clock_in_at = self.start + timedelta(minutes=1)
        await self.session.flush()
        with self.assertRaises(HTTPException) as changed:
            await self.decide(request)
        self.assertEqual(changed.exception.status_code, 409)
        pending = await self.session.get(AttendanceCorrectionModel, request.id)
        self.assertEqual(pending.status, "PENDING")
