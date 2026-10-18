import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.filemaintenance.companies.infrastructure.db_model import CompanyModel
from app.filemaintenance.employees.application.related_use_case import _validate_assignment
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmploymentAssignmentLocationModel,
)
from app.filemaintenance.geofences.infrastructure.db_model import Geofence
from app.filemaintenance.location.infrastructure.db_model import Location


class FakeRepository:
    def __init__(self, record):
        self.record = record

    async def find_one(self, _criteria):
        return self.record

    async def find_all(self, *_criteria, **_kwargs):
        return [self.record]


class FakeUnitOfWork:
    def __init__(self, repositories, geofence, location):
        self.repositories = repositories
        self.session = SimpleNamespace(
            scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [geofence]))
        )

    def get_repo(self, _entity, model):
        return self.repositories[model]


class EmploymentAssignmentGeofenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.company_id = uuid4()
        self.employee_id = uuid4()
        self.location_id = uuid4()
        self.geofence_id = uuid4()
        self.location = SimpleNamespace(id=self.location_id, company_id=self.company_id)
        self.geofence = SimpleNamespace(
            id=self.geofence_id,
            company_id=self.company_id,
            location_id=self.location_id,
        )
        self.uow = FakeUnitOfWork({
            EmployeeModel: FakeRepository(SimpleNamespace(id=self.employee_id)),
            CompanyModel: FakeRepository(SimpleNamespace(id=self.company_id)),
            Location: FakeRepository(self.location),
        }, self.geofence, self.location)
        self.values = {
            "employee_id": self.employee_id,
            "company_id": self.company_id,
            "employment_type": "REGULAR",
            "employee_category": "RANK_AND_FILE",
            "hire_date": date(2026, 1, 1),
            "effective_from": date(2026, 1, 1),
            "authorized_geofence_ids": [self.geofence_id],
            "primary_location_id": uuid4(),
        }

    async def test_authorized_geofence_derives_the_legacy_location_field(self):
        await _validate_assignment(self.uow, self.values)

        self.assertEqual(self.values["primary_location_id"], self.location_id)

    async def test_geofence_from_another_company_is_rejected(self):
        self.geofence.company_id = uuid4()

        with self.assertRaisesRegex(ValueError, "does not belong to the selected company"):
            await _validate_assignment(self.uow, self.values)

    async def test_geofence_without_a_linked_location_is_rejected(self):
        self.geofence.location_id = None

        with self.assertRaisesRegex(ValueError, "must be linked to a location"):
            await _validate_assignment(self.uow, self.values)

    async def test_assigned_locations_must_belong_to_the_selected_company(self):
        self.values["location_ids"] = [self.location_id, uuid4()]

        with self.assertRaisesRegex(ValueError, "Assigned location does not belong"):
            await _validate_assignment(self.uow, self.values)

    async def test_geofence_location_must_be_in_the_assigned_locations(self):
        self.values["location_ids"] = [uuid4()]

        with self.assertRaisesRegex(ValueError, "must belong to an assigned location"):
            await _validate_assignment(self.uow, self.values)

    def test_assignment_location_table_enforces_company_scoped_foreign_keys(self):
        constraints = {
            constraint.name: {element.target_fullname for element in constraint.elements}
            for constraint in EmploymentAssignmentLocationModel.__table__.foreign_key_constraints
        }

        self.assertEqual(
            constraints["fk_assignment_locations_assignment_company"],
            {"hr.employment_assignments.id", "hr.employment_assignments.company_id"},
        )
        self.assertEqual(
            constraints["fk_assignment_locations_company_location"],
            {"core.locations.company_id", "core.locations.id"},
        )
