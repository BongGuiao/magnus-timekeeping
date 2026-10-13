import unittest
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.filemaintenance.employees.application.related_use_case import _validate_assignment
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
