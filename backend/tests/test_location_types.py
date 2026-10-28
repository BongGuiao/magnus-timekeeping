import unittest
from uuid import uuid4

from app.filemaintenance.location.application.location_type_use_case import (
    ListLocationTypesUseCase,
)
from app.filemaintenance.location.domain.entities.location_type import LocationTypeEntity
from app.filemaintenance.location.infrastructure.router import (
    LocationTypeCreateSchema,
    LocationTypeUpdateSchema,
)


class _FakeRepository:
    def __init__(self, values):
        self.values = values
        self.criteria = None

    async def find_all(self, *criteria, **_kwargs):
        self.criteria = criteria
        return self.values


class _FakeSession:
    async def scalar(self, _statement):
        return "OFFICE"


class _FakeUnitOfWork:
    def __init__(self, repository):
        self.repository = repository
        self.session = _FakeSession()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get_repo(self, *_args):
        return self.repository


class ListLocationTypesUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_active_types_by_default(self):
        company_id = uuid4()
        values = [
            LocationTypeEntity(
                company_id=company_id,
                location_type="OFFICE",
                display_name="Office",
                sort_order=10,
                is_default=True,
                is_active=True,
            )
        ]
        repository = _FakeRepository(values)

        result = await ListLocationTypesUseCase(_FakeUnitOfWork(repository)).execute(company_id)

        self.assertEqual(result, values)
        self.assertEqual(len(repository.criteria), 3)

    async def test_can_include_inactive_types_for_management(self):
        repository = _FakeRepository([])

        await ListLocationTypesUseCase(_FakeUnitOfWork(repository)).execute(uuid4(), True)

        self.assertEqual(len(repository.criteria), 2)

    async def test_can_include_deleted_types_for_management(self):
        repository = _FakeRepository([])

        await ListLocationTypesUseCase(_FakeUnitOfWork(repository)).execute(uuid4(), True, True)

        self.assertEqual(len(repository.criteria), 1)


class LocationTypeSchemaTests(unittest.TestCase):
    def test_create_normalizes_code_and_rejects_invalid_characters(self):
        payload = LocationTypeCreateSchema(
            company_id=uuid4(),
            location_type=" customer_site ",
            display_name="Customer site",
            sort_order=80,
        )
        self.assertEqual(payload.location_type, "CUSTOMER_SITE")

        with self.assertRaises(ValueError):
            LocationTypeCreateSchema(
                company_id=uuid4(),
                location_type="CUSTOMER SITE",
                display_name="Customer site",
                sort_order=80,
            )

    def test_inactive_type_cannot_be_default(self):
        with self.assertRaises(ValueError):
            LocationTypeCreateSchema(
                company_id=uuid4(),
                location_type="ARCHIVE",
                display_name="Archive",
                sort_order=90,
                is_default=True,
                is_active=False,
            )
        with self.assertRaises(ValueError):
            LocationTypeUpdateSchema(
                display_name="Archive",
                sort_order=90,
                is_default=True,
                is_active=False,
            )


if __name__ == "__main__":
    unittest.main()
