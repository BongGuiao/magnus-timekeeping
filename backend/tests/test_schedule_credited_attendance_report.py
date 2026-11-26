import unittest
from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.attendance.infrastructure.attendance_report_router import (
    AttendanceDetailReportRecord,
    AttendanceReportLeave,
    _attach_official_business,
    _load_report_leave,
)
from app.core.config import settings
from app.core.database import init_db_models
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import (
    LeaveApplicationDateModel,
    LeaveApplicationModel,
)


class ScheduleCreditedAttendanceReportTests(unittest.TestCase):
    def test_summary_splits_schedule_credit_from_approved_leave_and_ob(self) -> None:
        employee_id = uuid4()
        work_date = date(2026, 10, 8)
        timezone = ZoneInfo("Asia/Manila")
        record = AttendanceDetailReportRecord(
            attendance_id=None,
            employee_no="EMP-0001",
            employee_name="Test Employee",
            work_date=work_date,
            schedule_code="DAY",
            expected_clock_in_at=datetime(2026, 10, 8, 8, tzinfo=timezone),
            expected_clock_out_at=datetime(2026, 10, 8, 17, tzinfo=timezone),
            clock_in_at=None,
            clock_out_at=None,
            record_status="NO_PUNCH",
            attendance_mode="SCHEDULE_CREDITED",
            is_absent=False,
            work_type="REG",
            day_type="REG",
            late_minutes=0,
            undertime_minutes=0,
            worked_minutes=None,
            regular_overtime_minutes=0,
            night_differential_minutes=0,
            night_differential_overtime_minutes=0,
            overtime_applications=[],
            leave_applications=[
                AttendanceReportLeave(
                    application_no="LV-001",
                    leave_type="VL",
                    requested_minutes=120,
                    paid_minutes=60,
                    unpaid_minutes=60,
                    status="APPROVED",
                )
            ],
            official_business_requests=[],
        )
        request = SimpleNamespace(
            request_no="OB-001",
            requested_minutes=120,
            approved_minutes=120,
            status="APPROVED",
            start_at=datetime(2026, 10, 8, 13, tzinfo=timezone),
            end_at=datetime(2026, 10, 8, 15, tzinfo=timezone),
        )

        _attach_official_business(
            [(employee_id, record, 480)],
            {employee_id: [request]},
            work_date,
            work_date,
        )

        self.assertIsNone(record.clock_in_at)
        self.assertIsNone(record.clock_out_at)
        self.assertEqual(record.worked_minutes, 240)
        self.assertEqual(record.official_business_requests[0].credited_minutes, 120)

    def test_schedule_credit_is_not_reported_as_work_on_nonworking_holiday(self) -> None:
        employee_id = uuid4()
        work_date = date(2026, 10, 8)
        timezone = ZoneInfo("Asia/Manila")
        record = AttendanceDetailReportRecord(
            attendance_id=None,
            employee_no="EMP-0001",
            employee_name="Test Employee",
            work_date=work_date,
            schedule_code="DAY",
            expected_clock_in_at=datetime(2026, 10, 8, 8, tzinfo=timezone),
            expected_clock_out_at=datetime(2026, 10, 8, 17, tzinfo=timezone),
            clock_in_at=None,
            clock_out_at=None,
            record_status="NO_PUNCH",
            attendance_mode="SCHEDULE_CREDITED",
            is_absent=False,
            work_type="REG",
            day_type="RH",
            late_minutes=0,
            undertime_minutes=0,
            worked_minutes=None,
            regular_overtime_minutes=0,
            night_differential_minutes=0,
            night_differential_overtime_minutes=0,
            overtime_applications=[],
            leave_applications=[],
            official_business_requests=[],
        )

        _attach_official_business(
            [(employee_id, record, 480)],
            {},
            work_date,
            work_date,
        )

        self.assertEqual(record.worked_minutes, 0)


class AttendanceReportLeaveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        init_db_models()
        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.addAsyncCleanup(self.engine.dispose)
        self.connection = await self.engine.connect()
        self.addAsyncCleanup(self.connection.close)
        self.transaction = await self.connection.begin()
        self.addAsyncCleanup(self.transaction.rollback)
        for table in ("leave_types", "leave_applications", "leave_application_dates"):
            await self.connection.execute(text(
                f"CREATE TEMP TABLE {table} (LIKE leave_mgmt.{table} INCLUDING DEFAULTS)"
            ))
        await self.connection.execution_options(schema_translate_map={"leave_mgmt": "pg_temp"})
        self.session = AsyncSession(bind=self.connection, expire_on_commit=False)
        self.addAsyncCleanup(self.session.close)
        self.employee_id, self.leave_type_id = uuid4(), uuid4()
        await self.session.execute(text(
            "INSERT INTO leave_types (id, company_id, leave_code, leave_name, leave_category, unit_type, accrual_method, effective_from) "
            "VALUES (:id, :company, 'VL', 'Vacation', 'VACATION', 'DAY', 'NONE', '2026-01-01')"
        ), {"id": self.leave_type_id, "company": uuid4()})

    def application(self, number, start, end, *, status="APPROVED", employee_id=None, active=True):
        application = LeaveApplicationModel(
            id=uuid4(), application_no=number, employee_id=employee_id or self.employee_id,
            leave_type_id=self.leave_type_id, start_at=start, end_at=end, duration_type="DAY",
            requested_minutes=480, paid_minutes=360, unpaid_minutes=120, reason="Test",
            status=status, is_active=active,
        )
        self.session.add(application)
        return application

    async def test_leave_without_date_rows_appears_with_status_and_amounts(self):
        tz = ZoneInfo("Asia/Manila")
        self.application("APPROVED", datetime(2026, 12, 2, 8, tzinfo=tz), datetime(2026, 12, 2, 17, tzinfo=tz))
        self.application("PENDING", datetime(2026, 12, 3, 8, tzinfo=tz), datetime(2026, 12, 3, 17, tzinfo=tz), status="PENDING")
        self.application("OTHER", datetime(2026, 12, 2, 8, tzinfo=tz), datetime(2026, 12, 2, 17, tzinfo=tz), employee_id=uuid4())
        self.application("INACTIVE", datetime(2026, 12, 2, 8, tzinfo=tz), datetime(2026, 12, 2, 17, tzinfo=tz), active=False)
        await self.session.flush()
        result = await _load_report_leave(self.session, {self.employee_id}, date(2026, 12, 2), date(2026, 12, 3))
        leave = result[(self.employee_id, date(2026, 12, 2))]
        self.assertEqual([(item.application_no, item.status, item.paid_minutes, item.unpaid_minutes) for item in leave],
                         [("APPROVED", "APPROVED", 360, 120)])
        self.assertNotIn("has_daily_breakdown", leave[0].model_dump())
        self.assertEqual(result[(self.employee_id, date(2026, 12, 3))][0].status, "PENDING")
        record = AttendanceDetailReportRecord(
            attendance_id=None, employee_no="E1", employee_name="Employee", work_date=date(2026, 12, 2),
            schedule_code="DAY", expected_clock_in_at=datetime(2026, 12, 2, 8, tzinfo=tz),
            expected_clock_out_at=datetime(2026, 12, 2, 17, tzinfo=tz),
            clock_in_at=None, clock_out_at=None, record_status="NO_PUNCH", attendance_mode="SCHEDULE_CREDITED",
            is_absent=False, work_type="REG", day_type="REG", late_minutes=0, undertime_minutes=0,
            worked_minutes=None, regular_overtime_minutes=0, night_differential_minutes=0,
            night_differential_overtime_minutes=0, overtime_applications=[], leave_applications=leave,
            official_business_requests=[],
        )
        _attach_official_business([(self.employee_id, record, 480)], {}, date(2026, 12, 2), date(2026, 12, 2))
        self.assertEqual(record.worked_minutes, 480)

    async def test_explicit_dates_take_precedence_and_midnight_is_exclusive(self):
        tz = ZoneInfo("Asia/Manila")
        explicit = self.application("EXPLICIT", datetime(2026, 12, 2, 8, tzinfo=tz), datetime(2026, 12, 4, 17, tzinfo=tz))
        self.application("MIDNIGHT", datetime(2026, 12, 2, 12, tzinfo=tz), datetime(2026, 12, 3, 0, tzinfo=tz))
        self.session.add(LeaveApplicationDateModel(
            leave_application_id=explicit.id, leave_date=date(2026, 12, 4), requested_minutes=240,
            approved_paid_minutes=180, approved_unpaid_minutes=60,
        ))
        await self.session.flush()
        result = await _load_report_leave(self.session, {self.employee_id}, date(2026, 12, 2), date(2026, 12, 4))
        self.assertEqual([item.application_no for item in result[(self.employee_id, date(2026, 12, 2))]], ["MIDNIGHT"])
        self.assertNotIn((self.employee_id, date(2026, 12, 3)), result)
        self.assertEqual(result[(self.employee_id, date(2026, 12, 4))][0].paid_minutes, 180)
        narrow = await _load_report_leave(self.session, {self.employee_id}, date(2026, 12, 2), date(2026, 12, 2))
        self.assertEqual([item.application_no for item in narrow[(self.employee_id, date(2026, 12, 2))]], ["MIDNIGHT"])

    async def test_fallback_prorates_multi_day_minutes_without_double_counting(self):
        tz = ZoneInfo("Asia/Manila")
        self.application("OVERNIGHT", datetime(2026, 12, 2, 23, tzinfo=tz), datetime(2026, 12, 3, 1, tzinfo=tz))
        await self.session.flush()
        result = await _load_report_leave(self.session, {self.employee_id}, date(2026, 12, 2), date(2026, 12, 3))
        for day in (date(2026, 12, 2), date(2026, 12, 3)):
            leave = result[(self.employee_id, day)][0]
            self.assertEqual((leave.requested_minutes, leave.paid_minutes, leave.unpaid_minutes), (240, 180, 60))
