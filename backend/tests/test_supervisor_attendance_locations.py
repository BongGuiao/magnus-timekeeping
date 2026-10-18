import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.attendance.application.supervisor_attendance_location_use_cases import (
    ListSupervisorAttendanceLocationsInput,
    ListSupervisorAttendanceLocationsUseCase,
)
from app.attendance.application.supervisor_attendance_location_ports import (
    SupervisedEmployeeAttendanceQuery,
)
from app.attendance.domain.entities.supervisor_attendance_location import (
    AmbiguousSupervisorCompanyError,
    AttendancePunchLocation,
    EmployeeNotInSupervisorTeamError,
    SupervisorAttendanceLocations,
    attendance_punch_locations,
)
from app.attendance.infrastructure.attendance_dashboard_router import (
    SupervisorAttendanceLocationRequest,
    get_supervisor_attendance_locations,
)
from app.attendance.infrastructure.supervisor_attendance_location_repository import (
    SqlAlchemySupervisorAttendanceLocationRepository,
)


NOW = datetime(2026, 10, 18, 2, tzinfo=timezone.utc)
WORK_DATE = date(2026, 10, 17)


class FakeLocationRepository:
    def __init__(self, company_ids, punches=None):
        self.company_ids = company_ids
        self.punches = punches or []
        self.company_calls = []
        self.punch_calls = []

    async def list_supervised_employee_companies(self, supervisor_id, employee_code, current_date):
        self.company_calls.append((supervisor_id, employee_code, current_date))
        return self.company_ids

    async def list_punch_locations(self, query, current_date):
        self.punch_calls.append((query, current_date))
        return self.punches


class FakeUnitOfWork:
    def __init__(self, repository):
        self.team_locations = repository

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


class AttendancePunchLocationMappingTests(unittest.TestCase):
    def test_extracts_both_valid_clock_locations_and_ignores_invalid_coordinates(self):
        clock_in = datetime(2026, 10, 17, 1, tzinfo=timezone.utc)
        clock_out = datetime(2026, 10, 17, 10, tzinfo=timezone.utc)
        punches = attendance_punch_locations(
            attendance_id=uuid4(),
            employee_code="EMP001",
            employee_name="Test Employee",
            work_date=WORK_DATE,
            clock_in_at=clock_in,
            clock_out_at=clock_out,
            punch_metadata={
                "clock_in": {
                    "location_report": {
                        "latitude": 14.5995,
                        "longitude": 120.9842,
                        "accuracy_meters": 8.5,
                    },
                },
                "clock_out": {
                    "location_report": {
                        "latitude": 91,
                        "longitude": 120.9842,
                    },
                },
            },
        )

        self.assertEqual(len(punches), 1)
        self.assertEqual(punches[0].action, "CLOCK_IN")
        self.assertEqual(punches[0].punched_at, clock_in)
        self.assertEqual(punches[0].latitude, 14.5995)
        self.assertEqual(punches[0].accuracy_meters, 8.5)

    def test_ignores_reported_location_without_a_matching_punch_time(self):
        punches = attendance_punch_locations(
            attendance_id=uuid4(),
            employee_code="EMP001",
            employee_name="Test Employee",
            work_date=WORK_DATE,
            clock_in_at=None,
            clock_out_at=None,
            punch_metadata={
                "clock_in": {"location_report": {"latitude": 14.5, "longitude": 120.9}},
            },
        )
        self.assertEqual(punches, [])

    def test_extracts_geofence_validation_coordinates(self):
        clock_in = datetime(2026, 10, 16, 9, tzinfo=timezone.utc)
        punches = attendance_punch_locations(
            attendance_id=uuid4(),
            employee_code="EMP001",
            employee_name="Test Employee",
            work_date=WORK_DATE,
            clock_in_at=clock_in,
            clock_out_at=None,
            punch_metadata={
                "clock_in": {
                    "geofence_validation": {
                        "latitude": 15.1240533,
                        "longitude": 120.6102243,
                        "accuracy_meters": 20.0,
                        "company_id": "61f2a872-58ac-470e-b8b0-66f1813f2241",
                        "location_name": "ANGELES CITY PHILIPPINES",
                    },
                },
            },
        )

        self.assertEqual(len(punches), 1)
        self.assertEqual(punches[0].latitude, 15.1240533)
        self.assertEqual(punches[0].longitude, 120.6102243)
        self.assertEqual(punches[0].accuracy_meters, 20.0)


class ListSupervisorAttendanceLocationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.supervisor_id = uuid4()
        self.company_id = uuid4()
        self.input = ListSupervisorAttendanceLocationsInput(
            supervisor_employee_id=self.supervisor_id,
            employee_code="EMP001",
            work_date=WORK_DATE,
        )

    def make_use_case(self, company_ids, punches=None):
        repository = FakeLocationRepository(company_ids, punches)
        uow = FakeUnitOfWork(repository)
        use_case = ListSupervisorAttendanceLocationsUseCase(uow, clock=lambda: NOW)
        return use_case, repository

    async def test_passes_server_resolved_supervisor_company_employee_and_date_scope(self):
        expected_punch = AttendancePunchLocation(
            attendance_id=uuid4(),
            employee_code="EMP001",
            employee_name="Test Employee",
            work_date=WORK_DATE,
            action="CLOCK_IN",
            punched_at=NOW,
            latitude=14.5,
            longitude=120.9,
            accuracy_meters=None,
        )
        use_case, repository = self.make_use_case([self.company_id], [expected_punch])

        result = await use_case.execute(self.input)

        self.assertEqual(result.company_id, self.company_id)
        self.assertEqual(result.punches, [expected_punch])
        self.assertEqual(
            repository.company_calls,
            [(self.supervisor_id, "EMP001", date(2026, 10, 18))],
        )
        self.assertEqual(
            repository.punch_calls,
            [(
                SupervisedEmployeeAttendanceQuery(
                    supervisor_employee_id=self.supervisor_id,
                    company_id=self.company_id,
                    employee_code="EMP001",
                    work_date=WORK_DATE,
                ),
                date(2026, 10, 18),
            )],
        )

    async def test_rejects_an_employee_outside_the_supervisor_team(self):
        use_case, repository = self.make_use_case([])

        with self.assertRaises(EmployeeNotInSupervisorTeamError):
            await use_case.execute(self.input)

        self.assertEqual(repository.punch_calls, [])

    async def test_rejects_ambiguous_company_assignments(self):
        use_case, repository = self.make_use_case([self.company_id, uuid4()])

        with self.assertRaises(AmbiguousSupervisorCompanyError):
            await use_case.execute(self.input)

        self.assertEqual(repository.punch_calls, [])


class SupervisorAttendanceLocationsRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_uses_authenticated_supervisor_and_only_form_parameters(self):
        supervisor_id = uuid4()
        company_id = uuid4()
        locations = SupervisorAttendanceLocations(
            company_id=company_id,
            employee_code="EMP001",
            work_date=WORK_DATE,
            punches=[],
        )
        use_case = MagicMock(execute=AsyncMock(return_value=locations))

        response = await get_supervisor_attendance_locations(
            request=SupervisorAttendanceLocationRequest(
                employee_code=" EMP001 ",
                work_date=WORK_DATE,
            ),
            claims={
                "employee_id": str(supervisor_id),
                "role_codes": ["SUPERVISOR"],
            },
            use_case=use_case,
        )

        self.assertEqual(
            use_case.execute.await_args.args[0],
            ListSupervisorAttendanceLocationsInput(
                supervisor_employee_id=supervisor_id,
                employee_code="EMP001",
                work_date=WORK_DATE,
            ),
        )
        self.assertEqual(response.data.company_id, company_id)

    async def test_rejects_non_supervisor_before_accessing_location_data(self):
        use_case = MagicMock(execute=AsyncMock())

        with self.assertRaises(HTTPException) as raised:
            await get_supervisor_attendance_locations(
                request=SupervisorAttendanceLocationRequest(
                    employee_code="EMP001",
                    work_date=WORK_DATE,
                ),
                claims={
                    "employee_id": str(uuid4()),
                    "role_codes": ["MANAGER"],
                },
                use_case=use_case,
            )

        self.assertEqual(raised.exception.status_code, 403)
        use_case.execute.assert_not_awaited()


class SupervisorAttendanceLocationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_attendance_query_is_scoped_by_employee_company_and_supervisor(self):
        supervisor_id = uuid4()
        company_id = uuid4()
        company_result = MagicMock()
        company_result.scalars.return_value.all.return_value = [company_id]
        attendance_result = MagicMock()
        attendance_result.all.return_value = []
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[company_result, attendance_result])
        repository = SqlAlchemySupervisorAttendanceLocationRepository(session)
        query = SupervisedEmployeeAttendanceQuery(
            supervisor_employee_id=supervisor_id,
            company_id=company_id,
            employee_code="EMP001",
            work_date=WORK_DATE,
        )

        resolved_companies = await repository.list_supervised_employee_companies(
            supervisor_id,
            "EMP001",
            date(2026, 10, 18),
        )
        locations = await repository.list_punch_locations(
            query,
            date(2026, 10, 18),
        )

        attendance_query = session.execute.await_args_list[1].args[0]
        compiled = attendance_query.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        values = set(compiled.params.values())
        self.assertEqual(resolved_companies, [company_id])
        self.assertEqual(locations, [])
        self.assertIn("hr.employment_assignments.supervisor_employee_id", sql)
        self.assertIn("hr.employment_assignments.company_id", sql)
        self.assertIn("attendance.attendance_records.work_date", sql)
        self.assertIn("hr.employees.employee_no", sql)
        self.assertIn(supervisor_id, values)
        self.assertIn(company_id, values)
        self.assertIn("EMP001", values)
        self.assertIn(WORK_DATE, values)
        self.assertIn(date(2026, 10, 18), values)
