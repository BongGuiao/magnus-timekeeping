import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.payroll.application.use_cases import (
    PayrollSetupError,
    PayrollUseCases,
    UpdateCompensationInput,
)


class FakePayrollRepository:
    def __init__(self) -> None:
        self.update_calls: list[dict] = []
        self.result = object()

    async def update_compensation(self, **kwargs):
        self.update_calls.append(kwargs)
        return self.result


class PayrollCompensationUpdateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repository = FakePayrollRepository()
        self.use_cases = PayrollUseCases(self.repository)
        self.data = UpdateCompensationInput(
            compensation_id=uuid4(),
            base_rate=Decimal("25.00"),
            currency="PHP",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 1, 31),
            actor_id=uuid4(),
        )

    async def test_updates_compensation_with_valid_rate_and_period(self) -> None:
        result = await self.use_cases.update_compensation(self.data)

        self.assertIs(result, self.repository.result)
        self.assertEqual(len(self.repository.update_calls), 1)
        self.assertEqual(
            self.repository.update_calls[0],
            {
                "compensation_id": self.data.compensation_id,
                "base_rate": "25.00",
                "currency": "PHP",
                "effective_from": date(2026, 1, 1),
                "effective_to": date(2026, 1, 31),
                "actor_id": self.data.actor_id,
            },
        )

    async def test_rejects_nonpositive_base_rate(self) -> None:
        with self.assertRaisesRegex(PayrollSetupError, "greater than zero"):
            await self.use_cases.update_compensation(
                replace(self.data, base_rate=Decimal("0"))
            )
        self.assertEqual(self.repository.update_calls, [])

    async def test_rejects_end_date_before_start_date(self) -> None:
        with self.assertRaisesRegex(PayrollSetupError, "on or after"):
            await self.use_cases.update_compensation(
                replace(self.data, effective_to=date(2025, 12, 31))
            )
        self.assertEqual(self.repository.update_calls, [])


if __name__ == "__main__":
    unittest.main()
