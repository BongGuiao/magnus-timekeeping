import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.filemaintenance.employees.application.related_use_case import (
    CreateEmploymentAssignmentsBatchUseCase,
    _ensure_single_active_assignment,
    _validate_assignment,
)
from app.filemaintenance.employees.infrastructure.db_model import EmploymentAssignmentModel
from app.filemaintenance.payroll_groups.domain.entities.payroll_group import PayrollGroupEntity


class _FakeRepository:
    def __init__(self, entity_type: type, payroll_company_id):
        self.entity_type = entity_type
        self.payroll_company_id = payroll_company_id

    async def find_one(self, *_criteria):
        if self.entity_type is PayrollGroupEntity:
            return SimpleNamespace(company_id=self.payroll_company_id)
        return SimpleNamespace()


class _FakeUnitOfWork:
    def __init__(self, payroll_company_id):
        self.payroll_company_id = payroll_company_id

    def get_repo(self, entity_type, _model_type):
        return _FakeRepository(entity_type, self.payroll_company_id)


class EmploymentAssignmentPayrollGroupTests(unittest.IsolatedAsyncioTestCase):
    async def test_assignment_batch_rejects_duplicate_employee_company_rows(self):
        employee_id = uuid4()
        company_id = uuid4()

        class UnopenedUnitOfWork:
            async def __aenter__(self):
                return self

            async def __aexit__(self, _exc_type, _exc_value, _traceback):
                return None

        rows = [
            {
                "row_number": row_number,
                "assignment": {
                    "employee_id": str(employee_id),
                    "company_id": str(company_id),
                    "employment_type": "REGULAR",
                    "employee_category": "RANK_AND_FILE",
                    "hire_date": "2026-01-01",
                    "effective_from": "2026-01-01",
                },
            }
            for row_number in (2, 3)
        ]

        with self.assertRaisesRegex(ValueError, "CSV row 3:.*duplicated in this file"):
            await CreateEmploymentAssignmentsBatchUseCase(UnopenedUnitOfWork()).execute(rows)

    async def test_assignment_rejects_a_second_active_assignment(self):
        session = SimpleNamespace(scalar=AsyncMock(return_value=uuid4()))
        uow = SimpleNamespace(session=session)

        with self.assertRaisesRegex(ValueError, "only one active employment assignment"):
            await _ensure_single_active_assignment(
                uow,
                {"employee_id": uuid4(), "status": "ACTIVE", "is_active": True},
            )

    async def test_inactive_assignment_does_not_conflict_with_active_assignment(self):
        session = SimpleNamespace(scalar=AsyncMock())
        uow = SimpleNamespace(session=session)

        await _ensure_single_active_assignment(
            uow,
            {"employee_id": uuid4(), "status": "INACTIVE", "is_active": True},
        )

        session.scalar.assert_not_awaited()

    async def test_assignment_rejects_payroll_group_from_another_company(self):
        company_id = uuid4()
        values = {
            "employee_id": uuid4(),
            "company_id": company_id,
            "employment_type": "REGULAR",
            "employee_category": "RANK_AND_FILE",
            "hire_date": date(2026, 1, 1),
            "effective_from": date(2026, 1, 1),
            "payroll_group_id": uuid4(),
        }

        with self.assertRaisesRegex(ValueError, "does not belong to the selected company"):
            await _validate_assignment(_FakeUnitOfWork(uuid4()), values)

    def test_assignment_payroll_group_foreign_key_targets_payroll_group_table(self):
        payroll_group_constraint = next(
            constraint
            for constraint in EmploymentAssignmentModel.__table__.foreign_key_constraints
            if constraint.name == "fk_assignment_payroll_group"
        )

        self.assertEqual(
            next(iter(payroll_group_constraint.elements)).target_fullname,
            "payroll.payroll_groups.id",
        )
