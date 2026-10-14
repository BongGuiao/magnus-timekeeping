import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.filemaintenance.leaves.application.leave_records_use_case import (
    _validate_entitlement_grant,
)


class QueryResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class EmployeeEntitlementEligibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_grant_allowed_after_minimum_service_months(self) -> None:
        company_id = uuid4()
        employee_id = uuid4()
        leave_type_id = uuid4()
        assignment = SimpleNamespace(
            company_id=company_id,
            hire_date=date(2025, 4, 9),
            primary_location_id=uuid4(),
        )
        leave_type = SimpleNamespace(
            company_id=company_id,
            is_active=True,
            status="ACTIVE",
            effective_from=date(2025, 1, 1),
            effective_to=None,
            minimum_service_months=6,
        )
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[QueryResult(assignment), QueryResult(leave_type)])
        )

        await _validate_entitlement_grant(
            session,
            employee_id,
            leave_type_id,
            date(2025, 10, 9),
        )

    async def test_grant_rejected_before_minimum_service_months(self) -> None:
        company_id = uuid4()
        assignment = SimpleNamespace(
            company_id=company_id,
            hire_date=date(2025, 4, 10),
            primary_location_id=uuid4(),
        )
        leave_type = SimpleNamespace(
            company_id=company_id,
            is_active=True,
            status="ACTIVE",
            effective_from=date(2025, 1, 1),
            effective_to=None,
            minimum_service_months=6,
        )
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[QueryResult(assignment), QueryResult(leave_type)])
        )

        with self.assertRaisesRegex(ValueError, "completed 5 of 6 required service months"):
            await _validate_entitlement_grant(
                session,
                uuid4(),
                uuid4(),
                date(2025, 10, 9),
            )

    async def test_grant_rejected_when_leave_type_belongs_to_another_company(self) -> None:
        assignment = SimpleNamespace(
            company_id=uuid4(),
            hire_date=date(2020, 1, 1),
            primary_location_id=uuid4(),
        )
        leave_type = SimpleNamespace(company_id=uuid4())
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[QueryResult(assignment), QueryResult(leave_type)])
        )

        with self.assertRaisesRegex(ValueError, "does not belong to the employee's assigned company"):
            await _validate_entitlement_grant(
                session,
                uuid4(),
                uuid4(),
                date(2025, 10, 9),
            )
