import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

from app.payroll.application.statutory_schedule_inputs import (
    ContributionBracketInput,
    ContributionScheduleInput,
)
from app.payroll.application.statutory_schedule_use_cases import StatutoryScheduleUseCases


def schedule(status: str = "DRAFT", effective_from: date = date(2026, 1, 1)):
    return SimpleNamespace(
        id=uuid4(),
        program_code="SSS",
        schedule_name="Draft schedule",
        effective_from=effective_from,
        effective_to=None,
        source_reference="Official schedule reference",
        status=status,
        created_at=datetime.now(timezone.utc),
        created_by=None,
        updated_at=datetime.now(timezone.utc),
        updated_by=None,
        row_version=1,
    )


class StatutoryScheduleUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repository = SimpleNamespace(
            create_contribution_schedule=AsyncMock(return_value=schedule()),
            get_contribution_schedule=AsyncMock(),
            list_contribution_schedules=AsyncMock(return_value=[]),
            list_contribution_brackets=AsyncMock(return_value=[]),
            set_contribution_schedule_status=AsyncMock(return_value=schedule("ACTIVE")),
            create_contribution_bracket=AsyncMock(),
        )
        self.use_cases = StatutoryScheduleUseCases(self.repository)
        self.actor_id = uuid4()

    async def test_creates_contribution_schedule_as_trimmed_draft_data(self) -> None:
        data = ContributionScheduleInput(
            program_code="SSS",
            schedule_name="  SSS Schedule  ",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            source_reference="  Official source  ",
            actor_id=self.actor_id,
        )

        await self.use_cases.create_contribution_schedule(data)

        self.repository.create_contribution_schedule.assert_awaited_once_with(
            program_code="SSS",
            schedule_name="SSS Schedule",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            source_reference="Official source",
            actor_id=self.actor_id,
        )

    async def test_rejects_editing_active_schedule(self) -> None:
        active = schedule("ACTIVE")
        self.repository.get_contribution_schedule.return_value = active
        data = ContributionScheduleInput(
            program_code="SSS",
            schedule_name="Updated",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            source_reference="Official source",
            actor_id=self.actor_id,
        )

        with self.assertRaisesRegex(ValueError, "Only draft schedules"):
            await self.use_cases.update_contribution_schedule(active.id, data)

    async def test_activation_requires_complete_bracket_ranges(self) -> None:
        draft = schedule()
        self.repository.get_contribution_schedule.return_value = draft
        self.repository.list_contribution_brackets.return_value = [
            SimpleNamespace(
                bracket_number=1,
                compensation_min=Decimal("1.00"),
                compensation_max=None,
            )
        ]

        with self.assertRaisesRegex(ValueError, "must begin at zero"):
            await self.use_cases.activate_contribution_schedule(draft.id, self.actor_id)

        self.repository.set_contribution_schedule_status.assert_not_awaited()

    async def test_brackets_can_only_be_created_for_draft_schedule(self) -> None:
        active = schedule("ACTIVE")
        self.repository.get_contribution_schedule.return_value = active
        bracket = ContributionBracketInput(
            bracket_number=1,
            compensation_min=Decimal("0"),
            compensation_max=None,
            contribution_base=Decimal("0"),
            employee_rate=Decimal("0"),
            employer_rate=Decimal("0"),
            employee_fixed_amount=Decimal("0"),
            employer_fixed_amount=Decimal("0"),
            employer_additional_fixed_amount=Decimal("0"),
        )

        with self.assertRaisesRegex(ValueError, "Only draft schedules"):
            await self.use_cases.create_contribution_bracket(active.id, bracket)

        self.repository.create_contribution_bracket.assert_not_awaited()

    async def test_pagibig_brackets_require_monthly_contribution_caps(self) -> None:
        pagibig_schedule = schedule()
        pagibig_schedule.program_code = "PAGIBIG"
        self.repository.get_contribution_schedule.return_value = pagibig_schedule
        bracket = ContributionBracketInput(
            bracket_number=1,
            compensation_min=Decimal("0"),
            compensation_max=None,
            contribution_base=Decimal("0"),
            employee_rate=Decimal("0.01"),
            employer_rate=Decimal("0.02"),
            employee_fixed_amount=Decimal("0"),
            employer_fixed_amount=Decimal("0"),
            employer_additional_fixed_amount=Decimal("0"),
        )

        with self.assertRaisesRegex(ValueError, "require employee and employer monthly"):
            await self.use_cases.create_contribution_bracket(pagibig_schedule.id, bracket)

        self.repository.create_contribution_bracket.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
