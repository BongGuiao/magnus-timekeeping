import unittest
import os
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.attendance.application import automatic_absence as absence
from app.attendance.application.use_case import (
    ClockAttendanceInputDTO,
    ClockAttendanceUseCase,
    ScheduleDayConfiguration,
)
from app.attendance.infrastructure.attendance_merge_queries import not_merged_source
from app.attendance.infrastructure.db_model import AttendanceModel
from app.attendance.infrastructure.offline_gateway import TransactionAttendanceUow
from app.auth.infrastructure.db_model import UserModel
from app.core.database import AsyncSessionLocal, engine, init_db_models
from app.enrollment.domain.entities.enrollment import EnrollmentStatus
from app.enrollment.infrastructure.db_model import FaceEnrollmentModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.schedule.application.emergency_schedule_use_cases import _blocks_emergency_schedule
from app.filemaintenance.schedule.infrastructure.db_model import ScheduleTemplateModel

MANILA = ZoneInfo("Asia/Manila")
WORK_DATE = date(2026, 11, 25)
START = datetime(2026, 11, 25, 9, tzinfo=MANILA)
END = START + timedelta(hours=9)


class AutomaticAbsenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id, self.employee_id = uuid4(), uuid4()
        self.schedule = ScheduleDayConfiguration(
            work_type="REG", expected_clock_in_at=START, expected_clock_out_at=END,
            schedule_template_id=uuid4(), schedule_context={"ot_eligible": False},
        )
        self.records = []
        self.session = SimpleNamespace(
            scalars=AsyncMock(side_effect=lambda statement: SimpleNamespace(all=lambda: self.records)),
            scalar=AsyncMock(return_value=uuid4()),
            add=Mock(), flush=AsyncMock(),
        )
        self.patches = [
            patch.object(absence, "lock_attendance_user", new=AsyncMock()),
            patch.object(absence, "resolve_schedule_day", new=AsyncMock(return_value=self.schedule)),
            patch.object(absence, "resolve_attendance_day_type", new=AsyncMock(return_value="REG")),
            patch.object(absence, "_has_approved_exception", new=AsyncMock(return_value=False)),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def process(self, now, payroll_open=True):
        with patch.object(absence, "_payroll_is_open", new=AsyncMock(return_value=payroll_open)):
            return await absence.process_automatic_absence(
                self.session, self.user_id, self.employee_id, WORK_DATE, now,
            )

    async def test_absence_is_created_at_exactly_sixty_minutes(self):
        self.assertEqual(await self.process(START + timedelta(minutes=59, seconds=59)), "not_due")
        self.session.add.assert_not_called()
        self.assertEqual(await self.process(START + timedelta(minutes=60)), "created")
        record = self.session.add.call_args.args[0]
        self.assertTrue(record.is_absent)
        self.assertEqual(record.work_date, WORK_DATE)
        self.assertEqual(record.punch_metadata["automatic_absence"]["delay_minutes"], 60)

    async def test_approved_exception_or_nonworking_schedule_is_not_marked_absent(self):
        with patch.object(absence, "_has_approved_exception", new=AsyncMock(return_value=True)):
            self.assertEqual(await self.process(START + timedelta(hours=2)), "approved_exception")
        with patch.object(absence, "resolve_attendance_day_type", new=AsyncMock(return_value="RH")):
            self.assertEqual(await self.process(START + timedelta(hours=2)), "nonworking_day")
        self.session.add.assert_not_called()

    async def test_schedule_credited_and_missing_schedule_are_not_marked_absent(self):
        for schedule in (
            replace(self.schedule, attendance_mode="SCHEDULE_CREDITED"),
            replace(self.schedule, schedule_template_id=None),
        ):
            with self.subTest(schedule=schedule), patch.object(
                absence, "resolve_schedule_day", new=AsyncMock(return_value=schedule),
            ):
                self.assertEqual(await self.process(START + timedelta(hours=2)), "no_punch_schedule")
        self.session.add.assert_not_called()

    async def test_existing_valid_punch_prevents_absence(self):
        self.records = [AttendanceModel(
            user_id=self.user_id, work_date=WORK_DATE, record_status="VALID", clock_in_at=START,
        )]
        self.assertEqual(await self.process(START + timedelta(hours=2)), "attendance_exists")
        self.session.add.assert_not_called()

    async def test_approved_exception_clears_only_generated_absence(self):
        record = AttendanceModel(
            user_id=self.user_id, work_date=WORK_DATE, record_status="VALID", is_absent=True,
            is_locked=False, expected_clock_out_at=END,
            punch_metadata={"automatic_absence": {"recorded_at": START.isoformat()}},
        )
        self.records = [record]
        with patch.object(absence, "_has_approved_exception", new=AsyncMock(return_value=True)):
            self.assertEqual(await self.process(START + timedelta(hours=2)), "cleared")
        self.assertFalse(record.is_absent)
        self.assertEqual(record.record_status, "VOID")
        self.assertEqual(record.punch_metadata["automatic_absence"]["clear_reason"], "approved_leave_or_official_business")

    async def test_closed_payroll_is_not_changed(self):
        self.assertEqual(await self.process(START + timedelta(hours=2), payroll_open=False), "payroll_closed")
        self.session.add.assert_not_called()

    async def test_calculated_or_exported_cutoff_is_not_open(self):
        cutoff = SimpleNamespace(id=uuid4(), status="OPEN", export_batch_id=None)
        with patch.object(absence, "require_attendance_open", new=AsyncMock(return_value=[cutoff])):
            session = SimpleNamespace(scalar=AsyncMock(return_value=None))
            self.assertTrue(await absence._payroll_is_open(session, self.employee_id, WORK_DATE, START))
            session.scalar.return_value = uuid4()
            self.assertFalse(await absence._payroll_is_open(session, self.employee_id, WORK_DATE, START))
            cutoff.export_batch_id = uuid4()
            self.assertFalse(await absence._payroll_is_open(session, self.employee_id, WORK_DATE, START))

    async def test_a_later_schedule_clears_an_absence_until_the_new_deadline(self):
        record = AttendanceModel(
            user_id=self.user_id, work_date=WORK_DATE, record_status="VALID", is_absent=True,
            is_locked=False, expected_clock_out_at=END,
            punch_metadata={"automatic_absence": {"recorded_at": START.isoformat()}},
        )
        self.records = [record]
        later = replace(
            self.schedule, expected_clock_in_at=START + timedelta(hours=3),
            expected_clock_out_at=END + timedelta(hours=3),
        )
        with patch.object(absence, "resolve_schedule_day", new=AsyncMock(return_value=later)):
            self.assertEqual(await self.process(START + timedelta(hours=2)), "cleared_schedule")
        self.assertFalse(record.is_absent)
        self.assertEqual(record.punch_metadata["automatic_absence"]["clear_reason"], "schedule_changed")


@unittest.skipUnless(os.getenv("RUN_AUTOMATIC_ABSENCE_DB_TESTS") == "1", "Requires a migrated test database.")
class AutomaticAbsenceDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_late_clock_in_updates_the_generated_record(self):
        init_db_models()
        session = AsyncSessionLocal()
        try:
            await session.begin()
            template = (await session.execute(
                select(ScheduleTemplateModel.id, ScheduleTemplateModel.company_id).limit(1)
            )).first()
            if template is None:
                self.skipTest("Requires a schedule template.")
            template_id, company_id = template
            employee_id, user_id = uuid4(), uuid4()
            session.add(EmployeeModel(
                id=employee_id, employee_no="TEST-" + uuid4().hex[:16],
                first_name="Synthetic", last_name="Test",
            ))
            await session.flush()
            session.add(UserModel(
                id=user_id, employee_id=employee_id, username="test-" + uuid4().hex,
                password_hash="synthetic", account_status="ACTIVE",
            ))
            session.add(EmploymentAssignmentModel(
                employee_id=employee_id, company_id=company_id, employment_type="REGULAR",
                employee_category="REGULAR", hire_date=WORK_DATE, effective_from=WORK_DATE, status="ACTIVE",
            ))
            session.add(FaceEnrollmentModel(
                employee_id=employee_id, face_encoding=[0.0] * 128, status=EnrollmentStatus.ENROLLED,
            ))
            await session.flush()
            schedule = ScheduleDayConfiguration(
                work_type="REG", expected_clock_in_at=START, expected_clock_out_at=END,
                schedule_template_id=template_id, schedule_context={"ot_eligible": False},
            )
            face = SimpleNamespace(
                extract_face_encoding=Mock(return_value=[0.0] * 128),
                find_best_match=Mock(return_value=(employee_id, 0.0)),
            )
            clock = ClockAttendanceUseCase(TransactionAttendanceUow(session), face)
            with (
                patch.object(absence, "_payroll_is_open", new=AsyncMock(return_value=True)),
                patch.object(absence, "resolve_schedule_day", new=AsyncMock(return_value=schedule)),
                patch.object(absence, "resolve_attendance_day_type", new=AsyncMock(return_value="REG")),
                patch.object(absence, "_has_approved_exception", new=AsyncMock(return_value=False)),
                patch.object(clock, "_resolve_schedule_day", new=AsyncMock(return_value=schedule)),
                patch.object(clock, "_resolve_day_type", new=AsyncMock(return_value="REG")),
            ):
                self.assertEqual(await absence.process_automatic_absence(
                    session, user_id, employee_id, WORK_DATE, START + timedelta(minutes=60),
                ), "created")
                record = await session.scalar(select(AttendanceModel).where(AttendanceModel.user_id == user_id))
                record_id = record.id
                result = await clock.execute(ClockAttendanceInputDTO(
                    user_id=user_id, image_bytes=b"synthetic", captured_at=START + timedelta(minutes=75),
                ))
                await session.refresh(record)
                self.assertEqual(result.action, "clock_in")
                self.assertEqual(record.id, record_id)
                self.assertFalse(record.is_absent)
                self.assertEqual(record.clock_in_at, START + timedelta(minutes=75))
                self.assertEqual(record.late_minutes, 75)
                rows = (await session.scalars(select(AttendanceModel).where(AttendanceModel.user_id == user_id))).all()
                self.assertEqual(len(rows), 1)
        finally:
            await session.rollback()
            await session.close()
            await engine.dispose()

    async def test_creation_is_idempotent_and_valid_punch_clears_generated_absence(self):
        init_db_models()
        session = AsyncSessionLocal()
        try:
            await session.begin()
            template = (await session.execute(
                select(ScheduleTemplateModel.id, ScheduleTemplateModel.company_id).limit(1)
            )).first()
            if template is None:
                self.skipTest("Requires a schedule template.")
            template_id, company_id = template
            employee_id, user_id = uuid4(), uuid4()
            session.add(EmployeeModel(
                id=employee_id, employee_no="TEST-" + uuid4().hex[:16],
                first_name="Synthetic", last_name="Test",
            ))
            await session.flush()
            session.add(UserModel(
                id=user_id, employee_id=employee_id, username="test-" + uuid4().hex,
                password_hash="synthetic", account_status="ACTIVE",
            ))
            session.add(EmploymentAssignmentModel(
                employee_id=employee_id, company_id=company_id, employment_type="REGULAR",
                employee_category="REGULAR", hire_date=WORK_DATE, effective_from=WORK_DATE, status="ACTIVE",
            ))
            await session.flush()
            schedule = ScheduleDayConfiguration(
                work_type="REG", expected_clock_in_at=START, expected_clock_out_at=END,
                schedule_template_id=template_id, schedule_context={"ot_eligible": False},
            )
            now = START + timedelta(minutes=60)
            with (
                patch.object(absence, "_payroll_is_open", new=AsyncMock(return_value=True)),
                patch.object(absence, "resolve_schedule_day", new=AsyncMock(return_value=schedule)),
                patch.object(absence, "resolve_attendance_day_type", new=AsyncMock(return_value="REG")),
                patch.object(absence, "_has_approved_exception", new=AsyncMock(return_value=False)),
            ):
                self.assertEqual(await absence.process_automatic_absence(session, user_id, employee_id, WORK_DATE, now), "created")
                self.assertEqual(await absence.process_automatic_absence(session, user_id, employee_id, WORK_DATE, now), "already_recorded")
                blocking = await session.scalar(select(AttendanceModel.id).where(
                    AttendanceModel.user_id == user_id, _blocks_emergency_schedule(),
                ))
                self.assertIsNone(blocking)
                session.add(AttendanceModel(
                    user_id=user_id, work_date=WORK_DATE, record_status="VALID", clock_in_at=now,
                ))
                await session.flush()
                blocking = await session.scalar(select(AttendanceModel.id).where(
                    AttendanceModel.user_id == user_id, _blocks_emergency_schedule(),
                ))
                self.assertIsNotNone(blocking)
                self.assertEqual(await absence.process_automatic_absence(session, user_id, employee_id, WORK_DATE, now), "cleared")
                active = (await session.scalars(select(AttendanceModel).where(
                    AttendanceModel.user_id == user_id, not_merged_source(),
                ))).all()
                self.assertEqual(len(active), 1)
                self.assertIsNotNone(active[0].clock_in_at)
        finally:
            await session.rollback()
            await session.close()
            await engine.dispose()
