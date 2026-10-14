import unittest
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.filemaintenance.payroll_cutoffs.domain.entities.employee_cutoff_result import (
    AttendanceFact,
    ExceptionFact,
    LeaveDayFact,
    LeaveFact,
    OfficialBusinessFact,
    OvertimeFact,
    calculate_employee_cutoff_totals,
)


class EmployeeCutoffCalculationTests(unittest.TestCase):
    def test_aggregates_valid_attendance_and_approved_request_facts(self) -> None:
        employee_id = uuid4()
        timezone = ZoneInfo("Asia/Manila")
        totals = calculate_employee_cutoff_totals(
            employee_ids=[employee_id],
            attendance=[
                AttendanceFact(
                    employee_id=employee_id,
                    work_date=date(2026, 10, 1),
                    is_absent=False,
                    approved_hours_worked=8.0,
                    approved_night_diff=0,
                    scheduled_minutes=480,
                    work_type="REG",
                    day_type="REG",
                    late_minutes=12,
                    undertime_minutes=0,
                ),
                AttendanceFact(
                    employee_id=employee_id,
                    work_date=date(2026, 10, 2),
                    is_absent=True,
                    approved_hours_worked=None,
                    approved_night_diff=None,
                    scheduled_minutes=480,
                    work_type="REG",
                    day_type="REG",
                    late_minutes=0,
                    undertime_minutes=0,
                ),
            ],
            leaves=[
                LeaveFact(
                    employee_id=employee_id,
                    start_at=datetime(2026, 10, 1, tzinfo=timezone),
                    end_at=datetime(2026, 10, 4, tzinfo=timezone),
                    paid_minutes=0,
                    unpaid_minutes=0,
                    days=(
                        LeaveDayFact(date(2026, 10, 1), 240, 0),
                        LeaveDayFact(date(2026, 10, 3), 90, 0),
                    ),
                )
            ],
            overtime=[
                OvertimeFact(
                    employee_id,
                    date(2026, 10, 1),
                    90,
                    "REGULAR_OVERTIME",
                    "REG",
                    "REG",
                )
            ],
            official_business=[
                OfficialBusinessFact(
                    employee_id,
                    datetime(2026, 10, 1, 9, tzinfo=timezone),
                    datetime(2026, 10, 1, 13, tzinfo=timezone),
                    120,
                )
            ],
            exceptions=[ExceptionFact(employee_id)],
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 15),
        )

        self.assertEqual(len(totals), 1)
        self.assertEqual(totals[0].scheduled_days, 2)
        self.assertEqual(totals[0].paid_days, 2)
        self.assertEqual(totals[0].regular_minutes, 480)
        self.assertEqual(totals[0].absence_minutes, 480)
        self.assertEqual(totals[0].late_minutes, 12)
        self.assertEqual(totals[0].paid_leave_minutes, 330)
        self.assertEqual(totals[0].ordinary_ot_minutes, 90)
        self.assertEqual(totals[0].official_business_minutes, 120)

    def test_maps_rest_holiday_night_overtime_and_exception_totals(self) -> None:
        employee_id = uuid4()
        totals = calculate_employee_cutoff_totals(
            employee_ids=[employee_id],
            attendance=[
                AttendanceFact(
                    employee_id=employee_id,
                    work_date=date(2026, 10, 1),
                    is_absent=False,
                    approved_hours_worked=8,
                    approved_night_diff=2,
                    scheduled_minutes=480,
                    work_type="REST",
                    day_type="REG",
                    late_minutes=0,
                    undertime_minutes=0,
                ),
                AttendanceFact(
                    employee_id=employee_id,
                    work_date=date(2026, 10, 2),
                    is_absent=False,
                    approved_hours_worked=8,
                    approved_night_diff=0,
                    scheduled_minutes=480,
                    work_type="REG",
                    day_type="RH",
                    late_minutes=0,
                    undertime_minutes=0,
                ),
            ],
            leaves=[],
            overtime=[
                OvertimeFact(employee_id, date(2026, 10, 1), 30, "REGULAR_OVERTIME", "REST", "REG"),
                OvertimeFact(employee_id, date(2026, 10, 2), 45, "REGULAR_OVERTIME", "REG", "RH"),
                OvertimeFact(employee_id, date(2026, 10, 2), 60, "NIGHT_DIFFERENTIAL_OVERTIME", "REG", "RH"),
            ],
            official_business=[],
            exceptions=[ExceptionFact(employee_id), ExceptionFact(employee_id)],
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 15),
        )

        self.assertEqual(totals[0].rest_day_minutes, 480)
        self.assertEqual(totals[0].rest_day_ot_minutes, 30)
        self.assertEqual(totals[0].holiday_minutes, 480)
        self.assertEqual(totals[0].holiday_ot_minutes, 45)
        self.assertEqual(totals[0].night_regular_minutes, 120)
        self.assertEqual(totals[0].night_ot_minutes, 60)
        self.assertEqual(totals[0].exception_count, 2)

    def test_splits_approved_official_business_minutes_at_cutoff_boundary(self) -> None:
        employee_id = uuid4()
        timezone = ZoneInfo("Asia/Manila")
        totals = calculate_employee_cutoff_totals(
            employee_ids=[employee_id],
            attendance=[],
            leaves=[],
            overtime=[],
            official_business=[
                OfficialBusinessFact(
                    employee_id,
                    datetime(2026, 10, 15, 22, tzinfo=timezone),
                    datetime(2026, 10, 16, 2, tzinfo=timezone),
                    120,
                )
            ],
            exceptions=[],
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 15),
        )

        self.assertEqual(totals[0].official_business_minutes, 60)

    def test_split_cutoffs_do_not_duplicate_rounding_minutes(self) -> None:
        employee_id = uuid4()
        timezone = ZoneInfo("Asia/Manila")
        request = OfficialBusinessFact(
            employee_id,
            datetime(2026, 10, 15, 22, tzinfo=timezone),
            datetime(2026, 10, 16, 2, tzinfo=timezone),
            1,
        )
        first_cutoff = calculate_employee_cutoff_totals(
            [employee_id], [], [], [], [request], [], date(2026, 10, 1), date(2026, 10, 15)
        )
        second_cutoff = calculate_employee_cutoff_totals(
            [employee_id], [], [], [], [request], [], date(2026, 10, 16), date(2026, 10, 31)
        )

        self.assertEqual(
            first_cutoff[0].official_business_minutes
            + second_cutoff[0].official_business_minutes,
            1,
        )

    def test_employees_without_source_rows_receive_zero_totals(self) -> None:
        employee_id = uuid4()
        totals = calculate_employee_cutoff_totals(
            employee_ids=[employee_id],
            attendance=[],
            leaves=[],
            overtime=[],
            official_business=[],
            exceptions=[],
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 15),
        )

        self.assertEqual(totals[0].employee_id, employee_id)
        self.assertEqual(totals[0].regular_minutes, 0)
