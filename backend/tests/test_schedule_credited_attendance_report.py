import unittest
from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.attendance.infrastructure.attendance_report_router import (
    AttendanceDetailReportRecord,
    AttendanceReportLeave,
    _attach_official_business,
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
