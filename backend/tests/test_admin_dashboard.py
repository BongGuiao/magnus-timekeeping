import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import HTTPException

from app.attendance.application.admin_dashboard_use_cases import (
    GetAdminDashboardInput,
    GetAdminDashboardUseCase,
    total_weekly_minutes,
)
from app.attendance.domain.admin_dashboard_rules import NO_LOGOUT_GRACE, classify_attendance_exceptions
from app.attendance.domain.entities.admin_dashboard import (
    AdminDashboard,
    EmployeeWeeklyHours,
    PendingLeaveSummary,
    TeamAttendanceDay,
    WeeklyAttendanceSample,
)
from app.attendance.domain.entities.attendance_employee import AttendanceEmployee
from app.attendance.infrastructure.attendance_dashboard_router import get_admin_dashboard_snapshot

# Wednesday 2026-10-14 in Manila (UTC+8).
NOW = datetime(2026, 10, 14, 4, tzinfo=timezone.utc)


def employee(code, **changes):
    values = dict(id=uuid4(), employee_no=code, first_name="First" + code, last_name="Last" + code)
    values.update(changes)
    return AttendanceEmployee(**values)


SUPERVISOR = employee("SUP", preferred_name="The Boss")


def day(subject=None, **changes) -> TeamAttendanceDay:
    values = dict(
        employee=subject or employee("E1"), supervisor=SUPERVISOR, work_date=date(2026, 10, 13),
        clock_in_at=NOW - timedelta(days=1, hours=2), clock_out_at=None,
        expected_clock_out_at=NOW - timedelta(hours=7), is_absent=False, leave_type=None,
    )
    values.update(changes)
    return TeamAttendanceDay(**values)


class ClassifyAttendanceExceptionsTests(unittest.TestCase):
    def test_absent_employees_have_no_login_and_leave_days_are_never_exceptions(self):
        absent = day(is_absent=True, clock_in_at=None)
        on_leave = day(is_absent=True, leave_type="Vacation Leave")
        no_login, no_logout = classify_attendance_exceptions([absent, on_leave], NOW)
        self.assertEqual([item.employee for item in no_login], [absent.employee])
        self.assertEqual(no_logout, [])

    def test_no_logout_starts_six_hours_after_the_expected_time_out(self):
        expected = NOW - timedelta(days=1)
        boundary = expected + NO_LOGOUT_GRACE
        for now, flagged in (
            (boundary - timedelta(seconds=1), False),
            (boundary, True),
            (boundary + timedelta(seconds=1), True),
        ):
            with self.subTest(now=now):
                _, no_logout = classify_attendance_exceptions([day(expected_clock_out_at=expected)], now)
                self.assertEqual(len(no_logout), 1 if flagged else 0)

    def test_completed_or_unscheduled_days_are_not_missing_a_logout(self):
        done = day(clock_out_at=NOW)
        unscheduled = day(expected_clock_out_at=None)
        never_in = day(clock_in_at=None)
        self.assertEqual(classify_attendance_exceptions([done, unscheduled, never_in], NOW), ([], []))

    def test_exception_keeps_the_effective_punches_and_supervisor(self):
        item = classify_attendance_exceptions([day()], NOW)[1][0]
        self.assertEqual((item.supervisor, item.time_out), (SUPERVISOR, None))


class WeeklyMinutesTests(unittest.TestCase):
    def sample(self, subject, hours, nonpayable=0, **changes):
        start = datetime(2026, 10, 12, tzinfo=timezone.utc)
        values = dict(
            employee=subject, clock_in_at=start, clock_out_at=start + timedelta(hours=hours),
            punch_metadata={"break_calculation": {"net_nonpayable_minutes": nonpayable}},
        )
        values.update(changes)
        return WeeklyAttendanceSample(**values)

    def test_minutes_are_net_of_breaks_summed_per_employee_and_sorted_by_code(self):
        b, a = employee("B"), employee("A")
        totals = total_weekly_minutes([self.sample(b, 9, 60), self.sample(a, 9, 60), self.sample(a, 8)])
        self.assertEqual([(t.employee.employee_no, t.minutes_worked) for t in totals], [("A", 480 + 480), ("B", 480)])

    def test_incomplete_or_reversed_punches_are_skipped(self):
        subject = employee("A")
        totals = total_weekly_minutes([
            self.sample(subject, 8, clock_out_at=None),
            self.sample(subject, 8, clock_out_at=datetime(2026, 10, 11, tzinfo=timezone.utc)),
        ])
        self.assertEqual(totals, [])

    def test_hours_are_the_rounded_minutes_so_dashboard_and_employee_views_tally(self):
        self.assertEqual(EmployeeWeeklyHours(employee("A"), 481).hours_worked, round(481 / 60, 2))


class FakeDashboardRepository:
    def __init__(self, team=(), leaves=(), weekly=()):
        self.team, self.leaves, self.weekly, self.calls = list(team), list(leaves), list(weekly), []

    async def list_team_attendance(self, supervisor_employee_id, today, month_start):
        self.calls.append(("team", supervisor_employee_id, today, month_start))
        return self.team

    async def list_pending_leaves(self):
        self.calls.append(("leaves",))
        return self.leaves

    async def list_weekly_attendance(self, week_start, today):
        self.calls.append(("weekly", week_start, today))
        return self.weekly


class FakeUnitOfWork:
    def __init__(self, repository):
        self.dashboard = repository

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


class GetAdminDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_period_boundaries_follow_the_philippine_calendar_week_and_month(self):
        repository = FakeDashboardRepository()
        supervisor = uuid4()
        await GetAdminDashboardUseCase(FakeUnitOfWork(repository), clock=lambda: NOW).execute(
            GetAdminDashboardInput(supervisor)
        )
        self.assertEqual(repository.calls[0], ("team", supervisor, date(2026, 10, 14), date(2026, 10, 1)))
        self.assertEqual(repository.calls[2], ("weekly", date(2026, 10, 12), date(2026, 10, 14)))

    async def test_month_boundary_uses_manila_date_not_utc(self):
        late_utc = datetime(2026, 10, 31, 17, tzinfo=timezone.utc)
        repository = FakeDashboardRepository()
        await GetAdminDashboardUseCase(FakeUnitOfWork(repository), clock=lambda: late_utc).execute(
            GetAdminDashboardInput(uuid4())
        )
        self.assertEqual(repository.calls[0][2:], (date(2026, 11, 1), date(2026, 11, 1)))

    async def test_snapshot_combines_exceptions_leaves_and_weekly_hours(self):
        leave = PendingLeaveSummary(uuid4(), "LV-1", employee("L"), "Vacation Leave", NOW, NOW, 480, "PENDING")
        sample = WeeklyAttendanceSample(employee("A"), NOW - timedelta(hours=9), NOW, None)
        repository = FakeDashboardRepository(
            team=[day(), day(is_absent=True, clock_in_at=None)], leaves=[leave], weekly=[sample],
        )
        dashboard = await GetAdminDashboardUseCase(FakeUnitOfWork(repository), clock=lambda: NOW).execute(
            GetAdminDashboardInput(uuid4())
        )
        self.assertEqual((len(dashboard.no_logout), len(dashboard.no_login)), (1, 1))
        self.assertEqual(dashboard.pending_leaves, [leave])
        self.assertEqual(dashboard.weekly_hours[0].minutes_worked, 540)
        self.assertEqual(dashboard.refreshed_at, NOW)


class AdminDashboardRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_response_maps_names_hours_and_supervisor(self):
        subject = employee("E1", preferred_name="Ana")
        leave = PendingLeaveSummary(uuid4(), "LV-1", subject, "Sick Leave", NOW, NOW, 240, "PENDING")
        dashboard = AdminDashboard(
            no_logout=classify_attendance_exceptions([day(subject)], NOW)[1],
            pending_leaves=[leave], weekly_hours=[EmployeeWeeklyHours(subject, 481)], refreshed_at=NOW,
        )
        use_case = MagicMock(execute=AsyncMock(return_value=dashboard))
        employee_id = uuid4()

        response = await get_admin_dashboard_snapshot(
            claims={"role": "admin", "employee_id": str(employee_id)}, use_case=use_case,
        )

        self.assertEqual(use_case.execute.await_args.args[0], GetAdminDashboardInput(employee_id))
        data = response.data
        self.assertEqual((data.no_logout[0].employee_name, data.no_logout[0].supervisor_name), ("Ana", "The Boss"))
        self.assertEqual(data.pending_leaves[0].requested_minutes, 240)
        self.assertEqual((data.weekly_hours[0].minutes_worked, data.weekly_hours[0].hours_worked), (481, 8.02))

    async def test_non_admin_or_unlinked_accounts_are_forbidden(self):
        use_case = MagicMock(execute=AsyncMock())
        for claims in ({"role": "user", "employee_id": str(uuid4())}, {"role": "admin"}):
            with self.subTest(claims=claims), self.assertRaises(HTTPException) as error:
                await get_admin_dashboard_snapshot(claims=claims, use_case=use_case)
            self.assertEqual(error.exception.status_code, 403)
        use_case.execute.assert_not_awaited()
