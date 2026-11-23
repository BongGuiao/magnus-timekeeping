import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
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
    PunchedEmployeeToday,
    TeamAttendanceDay,
    WeeklyAttendanceSample,
)
from app.attendance.domain.entities.attendance_employee import AttendanceEmployee
from app.attendance.infrastructure.attendance_dashboard_router import (
    get_admin_dashboard_snapshot,
    get_team_dashboard_snapshot,
)
from app.attendance.infrastructure.admin_dashboard_repository import (
    SqlAlchemyAdminDashboardRepository,
)

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
    def test_recorded_absence_is_excluded_before_scheduled_clock_in(self):
        expected = NOW.astimezone(timezone(timedelta(hours=8)))
        absent = day(is_absent=True, clock_in_at=None, expected_clock_in_at=expected)
        for now, count in (
            (NOW - timedelta(seconds=1), 0),
            (NOW, 1),
            (NOW + timedelta(seconds=1), 1),
        ):
            with self.subTest(now=now):
                no_login, no_logout = classify_attendance_exceptions([absent], now)
                self.assertEqual(len(no_login), count)
                self.assertEqual(no_logout, [])

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

    def test_missing_clock_out_is_excluded_before_and_at_scheduled_clock_out(self):
        expected = NOW.astimezone(timezone(timedelta(hours=8)))
        attendance = day(expected_clock_out_at=expected)
        for now in (NOW - timedelta(seconds=1), NOW, NOW + timedelta(seconds=1)):
            with self.subTest(now=now):
                self.assertEqual(classify_attendance_exceptions([attendance], now), ([], []))

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
    def __init__(self, team=(), leaves=(), weekly=(), punched_today=0):
        self.team, self.leaves, self.weekly, self.calls = list(team), list(leaves), list(weekly), []
        self.punched_today = [
            PunchedEmployeeToday(employee(f"P{index:03}"), None, None)
            for index in range(punched_today)
        ]

    async def list_team_attendance(self, supervisor_employee_id, today, month_start):
        self.calls.append(("team", supervisor_employee_id, today, month_start))
        return self.team

    async def list_pending_leaves(self, supervisor_employee_id=None, today=None):
        self.calls.append(("leaves", supervisor_employee_id, today))
        return self.leaves

    async def list_weekly_attendance(self, week_start, today, supervisor_employee_id=None):
        self.calls.append(("weekly", week_start, today, supervisor_employee_id))
        return self.weekly

    async def list_employees_punched_today(self, today, approver_employee_id=None):
        self.calls.append(("punched_today", today, approver_employee_id))
        return self.punched_today


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
        self.assertEqual(repository.calls[2], ("weekly", date(2026, 10, 12), date(2026, 10, 14), None))

    async def test_team_scope_filters_pending_leaves_and_weekly_hours_to_the_supervisor(self):
        repository = FakeDashboardRepository()
        supervisor = uuid4()
        await GetAdminDashboardUseCase(FakeUnitOfWork(repository), clock=lambda: NOW).execute(
            GetAdminDashboardInput(supervisor, team_scope=True)
        )
        self.assertEqual(repository.calls[1], ("leaves", supervisor, date(2026, 10, 14)))
        self.assertEqual(
            repository.calls[2],
            ("weekly", date(2026, 10, 12), date(2026, 10, 14), supervisor),
        )
        self.assertEqual(
            repository.calls[3],
            ("punched_today", date(2026, 10, 14), supervisor),
        )

    async def test_punched_today_details_use_org_chart_approver_with_parent_fallback(self):
        manager_id, company_id = uuid4(), uuid4()
        fallback_employee_id, child_manager_employee_id = uuid4(), uuid4()
        parent_id, fallback_child_id, child_manager_unit_id = uuid4(), uuid4(), uuid4()
        fallback_clock_in = NOW - timedelta(hours=2)

        def org_unit(
            unit_id,
            *,
            manager_employee_id=None,
            parent_org_unit_id=None,
            manager_is_approver=True,
        ):
            return SimpleNamespace(
                id=unit_id,
                company_id=company_id,
                manager_employee_id=manager_employee_id,
                parent_org_unit_id=parent_org_unit_id,
                manager_is_approver=manager_is_approver,
                excluded_approval_org_unit_ids=[],
                deleted_at=None,
                is_active=True,
                status="ACTIVE",
                effective_from=date(2026, 1, 1),
                effective_to=None,
            )

        def punch_row(employee_id, employee_code, org_unit_id, clock_in_at):
            return SimpleNamespace(_mapping={
                "employee_id": employee_id,
                "employee_employee_no": employee_code,
                "employee_first_name": "First",
                "employee_middle_name": None,
                "employee_last_name": "Last",
                "employee_suffix": None,
                "employee_preferred_name": None,
                "company_id": company_id,
                "org_unit_id": org_unit_id,
                "clock_in_at": clock_in_at,
                "clock_out_at": None,
            })

        class FakePunchSession:
            async def execute(self, _statement):
                return SimpleNamespace(all=lambda: [
                    punch_row(fallback_employee_id, "FALLBACK", fallback_child_id, fallback_clock_in),
                    punch_row(child_manager_employee_id, "CHILD", child_manager_unit_id, NOW),
                ])

            async def scalars(self, _statement):
                return SimpleNamespace(all=lambda: [
                    org_unit(parent_id, manager_employee_id=manager_id),
                    org_unit(
                        fallback_child_id,
                        manager_employee_id=uuid4(),
                        parent_org_unit_id=parent_id,
                        manager_is_approver=False,
                    ),
                    org_unit(
                        child_manager_unit_id,
                        manager_employee_id=uuid4(),
                        parent_org_unit_id=parent_id,
                    ),
                ])

        punched = await SqlAlchemyAdminDashboardRepository(FakePunchSession()).list_employees_punched_today(
            date(2026, 10, 14),
            approver_employee_id=manager_id,
        )

        self.assertEqual(len(punched), 1)
        self.assertEqual(punched[0].employee.id, fallback_employee_id)
        self.assertEqual(punched[0].employee.employee_no, "FALLBACK")
        self.assertEqual(punched[0].clock_in_at, fallback_clock_in)

    async def test_punched_today_details_are_only_returned_for_organization_scope(self):
        organization_repository = FakeDashboardRepository(punched_today=12)
        organization_dashboard = await GetAdminDashboardUseCase(
            FakeUnitOfWork(organization_repository), clock=lambda: NOW
        ).execute(GetAdminDashboardInput(uuid4()))
        self.assertEqual(organization_dashboard.employees_punched_today, 12)
        self.assertEqual(
            organization_repository.calls[3],
            ("punched_today", date(2026, 10, 14), None),
        )
        self.assertEqual(len(organization_dashboard.punched_employees_today), 12)

        supervisor = uuid4()
        team_repository = FakeDashboardRepository(punched_today=4)
        team_dashboard = await GetAdminDashboardUseCase(
            FakeUnitOfWork(team_repository), clock=lambda: NOW
        ).execute(GetAdminDashboardInput(supervisor, team_scope=True))
        self.assertEqual(team_dashboard.employees_punched_today, 4)
        self.assertEqual(
            team_repository.calls[3],
            ("punched_today", date(2026, 10, 14), supervisor),
        )
        self.assertEqual(team_dashboard.punched_employees_today, [])

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
            pending_leaves=[leave], weekly_hours=[EmployeeWeeklyHours(subject, 481)],
            employees_punched_today=1,
            punched_employees_today=[
                PunchedEmployeeToday(subject, NOW - timedelta(hours=8), NOW)
            ],
            refreshed_at=NOW,
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
        self.assertEqual(data.employees_punched_today, 1)
        self.assertEqual(data.punched_employees_today[0].employee_name, "Ana")
        self.assertEqual(data.punched_employees_today[0].clock_out_at, NOW)

    async def test_non_admin_or_unlinked_accounts_are_forbidden(self):
        use_case = MagicMock(execute=AsyncMock())
        for claims in ({"role": "user", "employee_id": str(uuid4())}, {"role": "admin"}):
            with self.subTest(claims=claims), self.assertRaises(HTTPException) as error:
                await get_admin_dashboard_snapshot(claims=claims, use_case=use_case)
            self.assertEqual(error.exception.status_code, 403)
        use_case.execute.assert_not_awaited()

    async def test_team_dashboard_requests_team_scoped_data(self):
        dashboard = AdminDashboard(refreshed_at=NOW)
        use_case = MagicMock(execute=AsyncMock(return_value=dashboard))
        employee_id = uuid4()
        await get_team_dashboard_snapshot(
            claims={"employee_id": str(employee_id)},
            use_case=use_case,
        )
        self.assertEqual(
            use_case.execute.await_args.args[0],
            GetAdminDashboardInput(employee_id, team_scope=True),
        )
