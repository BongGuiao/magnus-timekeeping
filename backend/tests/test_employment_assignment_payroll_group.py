import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.filemaintenance.employees.application.related_use_case import (
    CreateEmploymentAssignmentsBatchUseCase,
    _ensure_single_active_assignment,
    _validate_assignment,
)
from app.filemaintenance.employees.domain.entities.employment_assignment import EmploymentAssignmentEntity
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

    async def test_assignment_batch_overrides_an_existing_employee_company_assignment(self):
        employee_id = uuid4()
        company_id = uuid4()
        existing = EmploymentAssignmentEntity(
            employee_id=employee_id, company_id=company_id, employment_type="REGULAR",
            employee_category="RANK_AND_FILE", hire_date=date(2026, 1, 1),
            effective_from=date(2026, 1, 1), operational_group="ARCHIVE", id=uuid4(),
        )
        session = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(employee_id, company_id)])),
        )
        repo = SimpleNamespace(
            find_all=AsyncMock(return_value=[existing]),
            update=AsyncMock(side_effect=lambda entity: entity),
            add=AsyncMock(),
        )

        class FakeUnitOfWork:
            def __init__(self):
                self.session = session

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def get_repo(self, *_args):
                return repo

        async def fake_validate(_uow, values, _existing=None):
            values.setdefault("location_ids", [])
            values.setdefault("primary_location_id", None)
            values.setdefault("authorized_geofence_ids", [])

        module = "app.filemaintenance.employees.application.related_use_case"
        ensure_single_active = AsyncMock()
        with (
            patch(f"{module}._validate_assignment", AsyncMock(side_effect=fake_validate)) as validator,
            patch(f"{module}._ensure_single_active_assignment", ensure_single_active),
            patch(f"{module}._get_assignment_geofence_ids", AsyncMock(return_value=[])),
            patch(f"{module}._get_assignment_location_ids", AsyncMock(return_value=[])),
        ):
            items = await CreateEmploymentAssignmentsBatchUseCase(FakeUnitOfWork()).execute([
                {
                    "row_number": 2,
                    "assignment": {
                        "employee_id": str(employee_id),
                        "company_id": str(company_id),
                        "employment_type": "CONTRACTUAL",
                        "employee_category": "RANK_AND_FILE",
                        "hire_date": "2026-01-01",
                        "effective_from": "2026-02-01",
                    },
                },
            ])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].action, "UPDATE")
        self.assertIs(items[0].before, existing)
        self.assertEqual(items[0].assignment.id, existing.id)
        self.assertEqual(items[0].assignment.employment_type, "CONTRACTUAL")
        self.assertEqual(items[0].assignment.effective_from, date(2026, 2, 1))
        repo.add.assert_not_awaited()
        repo.update.assert_awaited_once()
        # Retention of the original company/group pair must be passed to validation.
        self.assertEqual(validator.await_args.args[2], (company_id, "ARCHIVE"))
        # The overridden assignment must be excluded from the single-active check.
        self.assertEqual(ensure_single_active.await_args.args[2], existing.id)

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
