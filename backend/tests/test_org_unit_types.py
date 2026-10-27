import unittest
from uuid import uuid4

from app.filemaintenance.org_unit.application.use_case import ListOrgUnitTypesUseCase
from app.filemaintenance.org_unit.domain.entities.org_unit_type import OrgUnitTypeEntity
from app.filemaintenance.org_unit.infrastructure.router import (
    OrgUnitTypeCreateSchema,
    OrgUnitTypeUpdateSchema,
)


class _FakeRepository:
    def __init__(self, values):
        self.values = values
        self.criteria = None

    async def find_all(self, *criteria, **_kwargs):
        self.criteria = criteria
        return self.values


class _FakeUnitOfWork:
    def __init__(self, repository):
        self.repository = repository

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get_repo(self, *_args):
        return self.repository


class ListOrgUnitTypesUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_active_types_from_the_lookup_repository(self):
        values = [
            OrgUnitTypeEntity(
                company_id=uuid4(),
                org_unit_type="DEPARTMENT",
                display_name="Department",
                sort_order=20,
                is_default=True,
                is_active=True,
            )
        ]
        repository = _FakeRepository(values)

        company_id = uuid4()
        result = await ListOrgUnitTypesUseCase(_FakeUnitOfWork(repository)).execute(company_id)

        self.assertEqual(result, values)
        self.assertEqual(len(repository.criteria), 2)


class OrgUnitTypeSchemaTests(unittest.TestCase):
    def test_create_normalizes_code_and_rejects_unknown_fields(self):
        payload = OrgUnitTypeCreateSchema(
            company_id=uuid4(),
            org_unit_type=" business_unit ",
            display_name="Business unit",
            sort_order=60,
        )
        self.assertEqual(payload.org_unit_type, "BUSINESS_UNIT")
        with self.assertRaises(ValueError):
            OrgUnitTypeCreateSchema(
                company_id=uuid4(),
                org_unit_type="TEAM",
                display_name="Team",
                sort_order=30,
                unexpected=True,
            )

    def test_inactive_type_cannot_be_marked_default(self):
        with self.assertRaises(ValueError):
            OrgUnitTypeCreateSchema(
                company_id=uuid4(),
                org_unit_type="ARCHIVE",
                display_name="Archive",
                sort_order=90,
                is_default=True,
                is_active=False,
            )
        with self.assertRaises(ValueError):
            OrgUnitTypeUpdateSchema(
                display_name="Archive",
                sort_order=90,
                is_default=True,
                is_active=False,
            )


if __name__ == "__main__":
    unittest.main()
