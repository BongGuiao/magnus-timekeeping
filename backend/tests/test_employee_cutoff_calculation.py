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
    ScheduledDayFact,
    calculate_employee_cutoff_totals,
)


class EmployeeCutoffCalculationTests(unittest.TestCase):
    def test_carries_forward_late_approved_paid_leave_from_previous_cutoff(self) -> None:
        employee_id = uuid4()
        timezone = ZoneInfo("Asia/Manila")
        totals = calculate_employee_cutoff_totals(
            employee_ids=[employee_id],
            attendance=[],
            leaves=[
                LeaveFact(
                    employee_id=employee_id,
                    start_at=datetime(2026, 10, 12, tzinfo=timezone),
                    end_at=datetime(2026, 10, 13, tzinfo=timezone),
                    paid_minutes=0,
                    unpaid_minutes=0,
                    days=(LeaveDayFact(date(2026, 10, 12), 480, 120),),
                    carry_forward=True,
                )
            ],
            overtime=[],
            official_business=[],
            exceptions=[],
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 15),
        )

        self.assertEqual(totals[0].paid_leave_minutes, 480)
        self.assertEqual(totals[0].unpaid_leave_minutes, 120)
        self.assertEqual(totals[0].paid_days, 1)

    def test_does_not_include_previous_cutoff_leave_without_carry_forward(self) -> None:
        employee_id = uuid4()
        timezone = ZoneInfo("Asia/Manila")
        totals = calculate_employee_cutoff_totals(
            employee_ids=[employee_id],
            attendance=[],
            leaves=[
                LeaveFact(
                    employee_id=employee_id,
                    start_at=datetime(2026, 10, 12, tzinfo=timezone),
                    end_at=datetime(2026, 10, 13, tzinfo=timezone),
                    paid_minutes=0,
                    unpaid_minutes=0,
                    days=(LeaveDayFact(date(2026, 10, 12), 480, 0),),
                )
            ],
            overtime=[],
            official_business=[],
            exceptions=[],
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 15),
        )

        self.assertEqual(totals[0].paid_leave_minutes, 0)

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
                    expected_clock_in_at=datetime(2026, 10, 2, 8, tzinfo=timezone),
                    expected_clock_out_at=datetime(2026, 10, 2, 17, tzinfo=timezone),
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
                    datetime(2026, 10, 2, 9, tzinfo=timezone),
                    datetime(2026, 10, 2, 13, tzinfo=timezone),
                    120,
                )
            ],
            exceptions=[ExceptionFact(employee_id)],
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 15),
        )

        self.assertEqual(len(totals), 1)
        self.assertEqual(totals[0].scheduled_days, 2)
        self.assertEqual(totals[0].required_work_minutes, 960)
        self.assertEqual(totals[0].paid_days, 2)
        self.assertEqual(totals[0].regular_minutes, 468)
        self.assertEqual(totals[0].absence_minutes, 480)
        self.assertEqual(totals[0].late_minutes, 12)
        self.assertEqual(totals[0].paid_leave_minutes, 330)
        self.assertEqual(totals[0].ordinary_ot_minutes, 90)
        self.assertEqual(totals[0].official_business_minutes, 120)

    def test_caps_regular_work_to_schedule_less_lateness_and_undertime(self) -> None:
        employee_id = uuid4()
        totals = calculate_employee_cutoff_totals(
            employee_ids=[employee_id],
            attendance=[
                AttendanceFact(
                    employee_id=employee_id,
                    work_date=date(2026, 10, 1),
                    is_absent=False,
                    approved_hours_worked=9,
                    approved_night_diff=8,
                    scheduled_minutes=480,
                    work_type="REG",
                    day_type="REG",
                    late_minutes=15,
                    undertime_minutes=15,
                )
            ],
            leaves=[],
            overtime=[
                OvertimeFact(
                    employee_id,
                    date(2026, 10, 1),
                    60,
                    "REGULAR_OVERTIME",
                    "REG",
                    "REG",
                )
            ],
            official_business=[],
            exceptions=[],
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 15),
        )

        self.assertEqual(totals[0].required_work_minutes, 480)
        self.assertEqual(totals[0].regular_minutes, 450)
        self.assertEqual(totals[0].night_regular_minutes, 450)
        self.assertEqual(totals[0].ordinary_ot_minutes, 60)

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
        self.assertEqual(totals[0].required_work_minutes, 0)

    def test_excludes_rest_and_nonworking_holidays_from_schedule_requirements(self) -> None:
        employee_id = uuid4()
        dates = [
            (date(2026, 10, 1), "REST", "REG"),
            (date(2026, 10, 2), "REG", "RH"),
            (date(2026, 10, 3), "REG", "DBL"),
            (date(2026, 10, 4), "REG", "SNW"),
            (date(2026, 10, 5), "REG", "REG"),
            (date(2026, 10, 6), "REG", "SWH"),
        ]
        totals = calculate_employee_cutoff_totals(
            employee_ids=[employee_id],
            attendance=[
                AttendanceFact(
                    employee_id=employee_id,
                    work_date=work_date,
                    is_absent=work_date != date(2026, 10, 6),
                    approved_hours_worked=None if work_date != date(2026, 10, 6) else 8,
                    approved_night_diff=0,
                    scheduled_minutes=480,
                    work_type=work_type,
                    day_type=day_type,
                    late_minutes=0,
                    undertime_minutes=0,
                )
                for work_date, work_type, day_type in dates
            ],
            leaves=[],
            overtime=[],
            official_business=[],
            exceptions=[],
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 15),
        )

        self.assertEqual(totals[0].scheduled_days, 2)
        self.assertEqual(totals[0].required_work_minutes, 960)
        self.assertEqual(totals[0].absence_minutes, 480)

    def _official_business_totals(self, attendance, requests, scheduled_days=(), period=(1, 15)):
        employee_id = attendance[0].employee_id if attendance else scheduled_days[0].employee_id
        return calculate_employee_cutoff_totals(
            [employee_id],
            attendance,
            [],
            [],
            requests,
            [],
            date(2026, 10, period[0]),
            date(2026, 10, period[1]),
            list(scheduled_days),
        )[0]

    def _attendance(self, employee_id, work_date, start, end, *, punch_in=None, punch_out=None,
                    absent=False, late=0, undertime=0):
        timezone = ZoneInfo("Asia/Manila")
        return AttendanceFact(
            employee_id=employee_id,
            work_date=work_date,
            is_absent=absent,
            approved_hours_worked=None if absent else 8.0,
            approved_night_diff=0,
            scheduled_minutes=480,
            work_type="REG",
            day_type="REG",
            late_minutes=late,
            undertime_minutes=undertime,
            expected_clock_in_at=start.replace(tzinfo=timezone),
            expected_clock_out_at=end.replace(tzinfo=timezone),
            clock_in_at=punch_in.replace(tzinfo=timezone) if punch_in else None,
            clock_out_at=punch_out.replace(tzinfo=timezone) if punch_out else None,
        )

    def test_official_business_outside_scheduled_shift_is_not_credited(self) -> None:
        # EMP-0001 2026-10-07: 5PM-2AM shift fully punched plus a 1PM-5PM official business.
        employee_id = uuid4()
        timezone = ZoneInfo("Asia/Manila")
        totals = self._official_business_totals(
            [
                self._attendance(
                    employee_id,
                    date(2026, 10, 7),
                    datetime(2026, 10, 7, 17),
                    datetime(2026, 10, 8, 2),
                    punch_in=datetime(2026, 10, 7, 17),
                    punch_out=datetime(2026, 10, 8, 2),
                )
            ],
            [
                OfficialBusinessFact(
                    employee_id,
                    datetime(2026, 10, 7, 13, tzinfo=timezone),
                    datetime(2026, 10, 7, 17, tzinfo=timezone),
                    240,
                )
            ],
        )

        self.assertEqual(totals.official_business_minutes, 0)
        self.assertEqual(totals.regular_minutes, 480)
        self.assertEqual(totals.required_work_minutes, 480)

    def test_official_business_excludes_time_already_punched(self) -> None:
        # Late 2 hours (10AM in); OB 8AM-12PM only covers the unpunched 8AM-10AM.
        employee_id = uuid4()
        timezone = ZoneInfo("Asia/Manila")
        totals = self._official_business_totals(
            [
                self._attendance(
                    employee_id,
                    date(2026, 10, 5),
                    datetime(2026, 10, 5, 8),
                    datetime(2026, 10, 5, 17),
                    punch_in=datetime(2026, 10, 5, 10),
                    punch_out=datetime(2026, 10, 5, 17),
                    late=120,
                )
            ],
            [
                OfficialBusinessFact(
                    employee_id,
                    datetime(2026, 10, 5, 8, tzinfo=timezone),
                    datetime(2026, 10, 5, 12, tzinfo=timezone),
                    240,
                )
            ],
        )

        self.assertEqual(totals.regular_minutes, 360)
        self.assertEqual(totals.official_business_minutes, 120)

    def test_official_business_is_capped_by_remaining_required_minutes(self) -> None:
        # Absent on a 9-hour window with 480 required minutes; two OBs cover the whole window.
        employee_id = uuid4()
        timezone = ZoneInfo("Asia/Manila")
        totals = self._official_business_totals(
            [
                self._attendance(
                    employee_id,
                    date(2026, 10, 6),
                    datetime(2026, 10, 6, 8),
                    datetime(2026, 10, 6, 17),
                    absent=True,
                )
            ],
            [
                OfficialBusinessFact(
                    employee_id,
                    datetime(2026, 10, 6, 12, tzinfo=timezone),
                    datetime(2026, 10, 6, 17, tzinfo=timezone),
                    300,
                ),
                OfficialBusinessFact(
                    employee_id,
                    datetime(2026, 10, 6, 8, tzinfo=timezone),
                    datetime(2026, 10, 6, 12, tzinfo=timezone),
                    240,
                ),
            ],
        )

        self.assertEqual(totals.official_business_minutes, 480)
        self.assertEqual(totals.absence_minutes, 480)

    def test_official_business_on_unrecorded_scheduled_day_requires_the_schedule(self) -> None:
        employee_id = uuid4()
        timezone = ZoneInfo("Asia/Manila")
        totals = self._official_business_totals(
            [],
            [
                OfficialBusinessFact(
                    employee_id,
                    datetime(2026, 10, 8, 8, tzinfo=timezone),
                    datetime(2026, 10, 8, 12, tzinfo=timezone),
                    240,
                )
            ],
            [
                ScheduledDayFact(
                    employee_id,
                    date(2026, 10, 8),
                    datetime(2026, 10, 8, 8, tzinfo=timezone),
                    datetime(2026, 10, 8, 17, tzinfo=timezone),
                    480,
                )
            ],
        )

        self.assertEqual(totals.official_business_minutes, 240)
        self.assertEqual(totals.scheduled_days, 1)
        self.assertEqual(totals.required_work_minutes, 480)

    def test_overnight_official_business_belongs_to_the_shift_work_date(self) -> None:
        employee_id = uuid4()
        timezone = ZoneInfo("Asia/Manila")
        request = OfficialBusinessFact(
            employee_id,
            datetime(2026, 10, 15, 22, tzinfo=timezone),
            datetime(2026, 10, 16, 2, tzinfo=timezone),
            120,
        )
        shift = ScheduledDayFact(
            employee_id,
            date(2026, 10, 15),
            datetime(2026, 10, 15, 22, tzinfo=timezone),
            datetime(2026, 10, 16, 7, tzinfo=timezone),
            480,
        )

        first = self._official_business_totals([], [request], [shift], period=(1, 15))
        second = self._official_business_totals([], [request], [shift], period=(16, 31))

        self.assertEqual(first.official_business_minutes, 120)
        self.assertEqual(second.official_business_minutes, 0)

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

    def test_non_absent_attendance_without_approved_time_is_marked_incomplete(self) -> None:
        employee_id = uuid4()
        totals = calculate_employee_cutoff_totals(
            employee_ids=[employee_id],
            attendance=[
                AttendanceFact(
                    employee_id=employee_id,
                    work_date=date(2026, 10, 1),
                    is_absent=False,
                    approved_hours_worked=None,
                    approved_night_diff=None,
                    scheduled_minutes=480,
                    work_type="REG",
                    day_type="REG",
                    late_minutes=0,
                    undertime_minutes=0,
                )
            ],
            leaves=[],
            overtime=[],
            official_business=[],
            exceptions=[],
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 15),
        )

        self.assertEqual(totals[0].regular_minutes, 0)
        self.assertEqual(totals[0].incomplete_time_source_count, 1)
