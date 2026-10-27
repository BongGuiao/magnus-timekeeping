from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.payroll.application.statutory_schedule_inputs import (
    ContributionBracketInput,
    WithholdingTaxBracketInput,
)
from app.payroll.domain.entities.statutory_schedules import (
    ContributionBracket,
    ContributionProgram,
    ContributionSchedule,
    WithholdingTaxBracket,
    WithholdingTaxSchedule,
)


class StatutoryScheduleRepository(Protocol):
    async def list_contribution_schedules(
        self, program_code: ContributionProgram | None
    ) -> list[ContributionSchedule]: ...

    async def get_contribution_schedule(self, schedule_id: UUID) -> ContributionSchedule: ...

    async def create_contribution_schedule(
        self,
        *,
        program_code: ContributionProgram,
        schedule_name: str,
        effective_from: date,
        effective_to: date | None,
        source_reference: str,
        actor_id: UUID,
    ) -> ContributionSchedule: ...

    async def update_contribution_schedule(
        self,
        *,
        schedule_id: UUID,
        schedule_name: str,
        effective_from: date,
        effective_to: date | None,
        source_reference: str,
        actor_id: UUID,
    ) -> ContributionSchedule: ...

    async def set_contribution_schedule_status(
        self, schedule_id: UUID, status: str, actor_id: UUID
    ) -> ContributionSchedule: ...

    async def delete_contribution_schedule(self, schedule_id: UUID) -> None: ...

    async def list_contribution_brackets(self, schedule_id: UUID) -> list[ContributionBracket]: ...

    async def get_contribution_bracket(self, bracket_id: UUID) -> ContributionBracket: ...

    async def create_contribution_bracket(
        self, *, schedule_id: UUID, values: ContributionBracketInput
    ) -> ContributionBracket: ...

    async def update_contribution_bracket(
        self, bracket_id: UUID, values: ContributionBracketInput
    ) -> ContributionBracket: ...

    async def delete_contribution_bracket(self, bracket_id: UUID) -> None: ...

    async def list_withholding_tax_schedules(self) -> list[WithholdingTaxSchedule]: ...

    async def get_withholding_tax_schedule(self, schedule_id: UUID) -> WithholdingTaxSchedule: ...

    async def create_withholding_tax_schedule(
        self,
        *,
        schedule_name: str,
        effective_from: date,
        effective_to: date | None,
        tax_exempt_benefit_limit: Decimal,
        calculation_basis: str,
        source_reference: str,
        actor_id: UUID,
    ) -> WithholdingTaxSchedule: ...

    async def update_withholding_tax_schedule(
        self,
        *,
        schedule_id: UUID,
        schedule_name: str,
        effective_from: date,
        effective_to: date | None,
        tax_exempt_benefit_limit: Decimal,
        calculation_basis: str,
        source_reference: str,
        actor_id: UUID,
    ) -> WithholdingTaxSchedule: ...

    async def set_withholding_tax_schedule_status(
        self, schedule_id: UUID, status: str, actor_id: UUID
    ) -> WithholdingTaxSchedule: ...

    async def delete_withholding_tax_schedule(self, schedule_id: UUID) -> None: ...

    async def list_withholding_tax_brackets(
        self, schedule_id: UUID
    ) -> list[WithholdingTaxBracket]: ...

    async def get_withholding_tax_bracket(self, bracket_id: UUID) -> WithholdingTaxBracket: ...

    async def create_withholding_tax_bracket(
        self, *, schedule_id: UUID, values: WithholdingTaxBracketInput
    ) -> WithholdingTaxBracket: ...

    async def update_withholding_tax_bracket(
        self, bracket_id: UUID, values: WithholdingTaxBracketInput
    ) -> WithholdingTaxBracket: ...

    async def delete_withholding_tax_bracket(self, bracket_id: UUID) -> None: ...
