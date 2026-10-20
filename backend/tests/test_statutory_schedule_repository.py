import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.payroll.infrastructure.statutory_schedule_repository import (
    SqlAlchemyStatutoryScheduleRepository,
)


class FakeUnitOfWork:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None


def draft_schedule(*, program_code: str | None = None, effective_to: date | None = None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        program_code=program_code,
        schedule_name="Test schedule",
        effective_from=date(2026, 1, 1),
        effective_to=effective_to,
        source_reference="Test source",
        status="DRAFT",
        created_at=now,
        created_by=None,
        updated_at=now,
        updated_by=None,
        row_version=1,
    )


class StatutoryScheduleRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_activate_open_ended_contribution_schedule(self) -> None:
        schedule = draft_schedule(program_code="PAGIBIG")
        bracket = SimpleNamespace(
            bracket_number=1,
            compensation_min=Decimal("0"),
            compensation_max=None,
        )
        session = SimpleNamespace(
            scalar=AsyncMock(side_effect=[schedule, None]),
            scalars=AsyncMock(return_value=[bracket]),
            flush=AsyncMock(),
        )
        repository = SqlAlchemyStatutoryScheduleRepository(FakeUnitOfWork(session))

        result = await repository.set_contribution_schedule_status(
            schedule.id, "ACTIVE", uuid4()
        )

        self.assertEqual(result.status, "ACTIVE")
        self.assertEqual(result.row_version, 2)
        self.assertEqual(session.scalar.await_count, 2)

    async def test_activate_open_ended_withholding_tax_schedule(self) -> None:
        schedule = draft_schedule()
        schedule.tax_exempt_benefit_limit = Decimal("0")
        bracket = SimpleNamespace(
            bracket_number=1,
            annual_income_min=Decimal("0"),
            annual_income_max=None,
        )
        session = SimpleNamespace(
            scalar=AsyncMock(side_effect=[schedule, None]),
            scalars=AsyncMock(return_value=[bracket]),
            flush=AsyncMock(),
        )
        repository = SqlAlchemyStatutoryScheduleRepository(FakeUnitOfWork(session))

        result = await repository.set_withholding_tax_schedule_status(
            schedule.id, "ACTIVE", uuid4()
        )

        self.assertEqual(result.status, "ACTIVE")
        self.assertEqual(result.row_version, 2)
        self.assertEqual(session.scalar.await_count, 2)
