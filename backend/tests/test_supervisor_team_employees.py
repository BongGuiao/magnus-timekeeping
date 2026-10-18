import unittest
from datetime import date, datetime, timezone
from uuid import uuid4

from app.attendance.application.supervisor_attendance_location_use_cases import (
    ListSupervisorTeamEmployeesInput,
    ListSupervisorTeamEmployeesUseCase,
)
from app.attendance.domain.entities.supervisor_attendance_location import SupervisedTeamEmployee


class FakeTeamEmployeeRepository:
    def __init__(self, employees: list[SupervisedTeamEmployee]):
        self.employees = employees
        self.calls: list[tuple[object, date]] = []

    async def list_supervised_employees(self, supervisor_id, current_date):
        self.calls.append((supervisor_id, current_date))
        return self.employees


class FakeUnitOfWork:
    def __init__(self, repository: FakeTeamEmployeeRepository):
        self.team_locations = repository

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


class ListSupervisorTeamEmployeesTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_employees_for_authenticated_supervisor_and_current_manila_date(self):
        supervisor_id = uuid4()
        employees = [
            SupervisedTeamEmployee(
                employee_id=uuid4(),
                employee_code="EMP001",
                employee_name="Test Employee",
            ),
        ]
        repository = FakeTeamEmployeeRepository(employees)
        use_case = ListSupervisorTeamEmployeesUseCase(
            FakeUnitOfWork(repository),
            clock=lambda: datetime(2026, 10, 18, 2, tzinfo=timezone.utc),
        )

        result = await use_case.execute(
            ListSupervisorTeamEmployeesInput(supervisor_employee_id=supervisor_id)
        )

        self.assertEqual(result, employees)
        self.assertEqual(repository.calls, [(supervisor_id, date(2026, 10, 18))])
