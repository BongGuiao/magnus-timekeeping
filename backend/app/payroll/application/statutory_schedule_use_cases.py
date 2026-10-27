from datetime import date
from decimal import Decimal
from uuid import UUID

from app.payroll.application.statutory_schedule_inputs import (
    ContributionBracketInput,
    ContributionScheduleInput,
    WithholdingTaxBracketInput,
    WithholdingTaxScheduleInput,
)
from app.payroll.application.statutory_schedule_ports import StatutoryScheduleRepository
from app.payroll.domain.entities.statutory_schedules import (
    ContributionBracket,
    ContributionProgram,
    ContributionSchedule,
    WithholdingTaxBracket,
    WithholdingTaxSchedule,
    validate_complete_bracket_ranges,
    validate_contribution_bracket_values,
    validate_schedule_values,
    validate_withholding_tax_bracket_values,
)


class StatutoryScheduleUseCases:
    def __init__(self, repository: StatutoryScheduleRepository):
        self._repository = repository

    async def list_contribution_schedules(
        self, program_code: ContributionProgram | None = None
    ) -> list[ContributionSchedule]:
        return await self._repository.list_contribution_schedules(program_code)

    async def get_contribution_schedule(self, schedule_id: UUID) -> ContributionSchedule:
        return await self._repository.get_contribution_schedule(schedule_id)

    async def create_contribution_schedule(
        self, data: ContributionScheduleInput
    ) -> ContributionSchedule:
        validate_schedule_values(
            schedule_name=data.schedule_name,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
            source_reference=data.source_reference,
        )
        return await self._repository.create_contribution_schedule(
            program_code=data.program_code,
            schedule_name=data.schedule_name.strip(),
            effective_from=data.effective_from,
            effective_to=data.effective_to,
            source_reference=data.source_reference.strip(),
            actor_id=data.actor_id,
        )

    async def update_contribution_schedule(
        self, schedule_id: UUID, data: ContributionScheduleInput
    ) -> ContributionSchedule:
        schedule = await self._repository.get_contribution_schedule(schedule_id)
        self._require_draft(schedule.status)
        if data.program_code != schedule.program_code:
            raise ValueError("A contribution schedule's program cannot be changed.")
        validate_schedule_values(
            schedule_name=data.schedule_name,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
            source_reference=data.source_reference,
        )
        return await self._repository.update_contribution_schedule(
            schedule_id=schedule_id,
            schedule_name=data.schedule_name.strip(),
            effective_from=data.effective_from,
            effective_to=data.effective_to,
            source_reference=data.source_reference.strip(),
            actor_id=data.actor_id,
        )

    async def delete_contribution_schedule(self, schedule_id: UUID) -> None:
        schedule = await self._repository.get_contribution_schedule(schedule_id)
        self._require_draft(schedule.status)
        await self._repository.delete_contribution_schedule(schedule_id)

    async def activate_contribution_schedule(
        self, schedule_id: UUID, actor_id: UUID
    ) -> ContributionSchedule:
        schedule = await self._repository.get_contribution_schedule(schedule_id)
        self._require_draft(schedule.status)
        brackets = await self._repository.list_contribution_brackets(schedule_id)
        validate_complete_bracket_ranges(
            [
                (bracket.bracket_number, bracket.compensation_min, bracket.compensation_max)
                for bracket in brackets
            ]
        )
        for other in await self._repository.list_contribution_schedules(schedule.program_code):
            if other.id != schedule.id and other.status == "ACTIVE" and self._periods_overlap(
                schedule.effective_from,
                schedule.effective_to,
                other.effective_from,
                other.effective_to,
            ):
                raise ValueError("An active schedule for this program already covers these dates.")
        return await self._repository.set_contribution_schedule_status(
            schedule_id, "ACTIVE", actor_id
        )

    async def retire_contribution_schedule(
        self, schedule_id: UUID, actor_id: UUID
    ) -> ContributionSchedule:
        schedule = await self._repository.get_contribution_schedule(schedule_id)
        if schedule.status != "ACTIVE":
            raise ValueError("Only active contribution schedules can be retired.")
        return await self._repository.set_contribution_schedule_status(
            schedule_id, "RETIRED", actor_id
        )

    async def list_contribution_brackets(self, schedule_id: UUID) -> list[ContributionBracket]:
        await self._repository.get_contribution_schedule(schedule_id)
        return await self._repository.list_contribution_brackets(schedule_id)

    async def get_contribution_bracket(self, bracket_id: UUID) -> ContributionBracket:
        return await self._repository.get_contribution_bracket(bracket_id)

    async def create_contribution_bracket(
        self, schedule_id: UUID, data: ContributionBracketInput
    ) -> ContributionBracket:
        schedule = await self._repository.get_contribution_schedule(schedule_id)
        self._require_draft(schedule.status)
        self._validate_contribution_bracket(data)
        self._validate_program_contribution_fields(schedule.program_code, data)
        return await self._repository.create_contribution_bracket(
            schedule_id=schedule_id, values=data
        )

    async def update_contribution_bracket(
        self, bracket_id: UUID, data: ContributionBracketInput
    ) -> ContributionBracket:
        bracket = await self._repository.get_contribution_bracket(bracket_id)
        schedule = await self._repository.get_contribution_schedule(bracket.schedule_id)
        self._require_draft(schedule.status)
        self._validate_contribution_bracket(data)
        self._validate_program_contribution_fields(schedule.program_code, data)
        return await self._repository.update_contribution_bracket(bracket_id, data)

    async def delete_contribution_bracket(self, bracket_id: UUID) -> None:
        bracket = await self._repository.get_contribution_bracket(bracket_id)
        schedule = await self._repository.get_contribution_schedule(bracket.schedule_id)
        self._require_draft(schedule.status)
        await self._repository.delete_contribution_bracket(bracket_id)

    async def list_withholding_tax_schedules(self) -> list[WithholdingTaxSchedule]:
        return await self._repository.list_withholding_tax_schedules()

    async def get_withholding_tax_schedule(self, schedule_id: UUID) -> WithholdingTaxSchedule:
        return await self._repository.get_withholding_tax_schedule(schedule_id)

    async def create_withholding_tax_schedule(
        self, data: WithholdingTaxScheduleInput
    ) -> WithholdingTaxSchedule:
        self._validate_tax_schedule(data)
        return await self._repository.create_withholding_tax_schedule(
            schedule_name=data.schedule_name.strip(),
            effective_from=data.effective_from,
            effective_to=data.effective_to,
            tax_exempt_benefit_limit=data.tax_exempt_benefit_limit,
            calculation_basis=data.calculation_basis,
            source_reference=data.source_reference.strip(),
            actor_id=data.actor_id,
        )

    async def update_withholding_tax_schedule(
        self, schedule_id: UUID, data: WithholdingTaxScheduleInput
    ) -> WithholdingTaxSchedule:
        schedule = await self._repository.get_withholding_tax_schedule(schedule_id)
        self._require_draft(schedule.status)
        self._validate_tax_schedule(data)
        return await self._repository.update_withholding_tax_schedule(
            schedule_id=schedule_id,
            schedule_name=data.schedule_name.strip(),
            effective_from=data.effective_from,
            effective_to=data.effective_to,
            tax_exempt_benefit_limit=data.tax_exempt_benefit_limit,
            calculation_basis=data.calculation_basis,
            source_reference=data.source_reference.strip(),
            actor_id=data.actor_id,
        )

    async def delete_withholding_tax_schedule(self, schedule_id: UUID) -> None:
        schedule = await self._repository.get_withholding_tax_schedule(schedule_id)
        self._require_draft(schedule.status)
        await self._repository.delete_withholding_tax_schedule(schedule_id)

    async def activate_withholding_tax_schedule(
        self, schedule_id: UUID, actor_id: UUID
    ) -> WithholdingTaxSchedule:
        schedule = await self._repository.get_withholding_tax_schedule(schedule_id)
        self._require_draft(schedule.status)
        brackets = await self._repository.list_withholding_tax_brackets(schedule_id)
        validate_complete_bracket_ranges(
            [
                (bracket.bracket_number, bracket.annual_income_min, bracket.annual_income_max)
                for bracket in brackets
            ]
        )
        for other in await self._repository.list_withholding_tax_schedules():
            if other.id != schedule.id and other.status == "ACTIVE" and self._periods_overlap(
                schedule.effective_from,
                schedule.effective_to,
                other.effective_from,
                other.effective_to,
            ):
                raise ValueError("An active withholding tax schedule already covers these dates.")
        return await self._repository.set_withholding_tax_schedule_status(
            schedule_id, "ACTIVE", actor_id
        )

    async def retire_withholding_tax_schedule(
        self, schedule_id: UUID, actor_id: UUID
    ) -> WithholdingTaxSchedule:
        schedule = await self._repository.get_withholding_tax_schedule(schedule_id)
        if schedule.status != "ACTIVE":
            raise ValueError("Only active withholding tax schedules can be retired.")
        return await self._repository.set_withholding_tax_schedule_status(
            schedule_id, "RETIRED", actor_id
        )

    async def list_withholding_tax_brackets(
        self, schedule_id: UUID
    ) -> list[WithholdingTaxBracket]:
        await self._repository.get_withholding_tax_schedule(schedule_id)
        return await self._repository.list_withholding_tax_brackets(schedule_id)

    async def get_withholding_tax_bracket(self, bracket_id: UUID) -> WithholdingTaxBracket:
        return await self._repository.get_withholding_tax_bracket(bracket_id)

    async def create_withholding_tax_bracket(
        self, schedule_id: UUID, data: WithholdingTaxBracketInput
    ) -> WithholdingTaxBracket:
        schedule = await self._repository.get_withholding_tax_schedule(schedule_id)
        self._require_draft(schedule.status)
        self._validate_tax_bracket(data)
        return await self._repository.create_withholding_tax_bracket(
            schedule_id=schedule_id, values=data
        )

    async def update_withholding_tax_bracket(
        self, bracket_id: UUID, data: WithholdingTaxBracketInput
    ) -> WithholdingTaxBracket:
        bracket = await self._repository.get_withholding_tax_bracket(bracket_id)
        schedule = await self._repository.get_withholding_tax_schedule(bracket.schedule_id)
        self._require_draft(schedule.status)
        self._validate_tax_bracket(data)
        return await self._repository.update_withholding_tax_bracket(bracket_id, data)

    async def delete_withholding_tax_bracket(self, bracket_id: UUID) -> None:
        bracket = await self._repository.get_withholding_tax_bracket(bracket_id)
        schedule = await self._repository.get_withholding_tax_schedule(bracket.schedule_id)
        self._require_draft(schedule.status)
        await self._repository.delete_withholding_tax_bracket(bracket_id)

    @staticmethod
    def _require_draft(status: str) -> None:
        if status != "DRAFT":
            raise ValueError("Only draft schedules can be edited or deleted.")

    @staticmethod
    def _periods_overlap(
        first_from: date,
        first_to: date | None,
        second_from: date,
        second_to: date | None,
    ) -> bool:
        return (
            (second_to is None or first_from <= second_to)
            and (first_to is None or second_from <= first_to)
        )

    @staticmethod
    def _validate_contribution_bracket(data: ContributionBracketInput) -> None:
        validate_contribution_bracket_values(
            bracket_number=data.bracket_number,
            compensation_min=data.compensation_min,
            compensation_max=data.compensation_max,
            contribution_base=data.contribution_base,
            employee_rate=data.employee_rate,
            employer_rate=data.employer_rate,
            employee_fixed_amount=data.employee_fixed_amount,
            employer_fixed_amount=data.employer_fixed_amount,
            employer_additional_fixed_amount=data.employer_additional_fixed_amount,
            employee_contribution_cap=data.employee_contribution_cap,
            employer_contribution_cap=data.employer_contribution_cap,
        )

    @staticmethod
    def _validate_program_contribution_fields(
        program_code: ContributionProgram, data: ContributionBracketInput
    ) -> None:
        has_caps = (
            data.employee_contribution_cap is not None
            and data.employer_contribution_cap is not None
        )
        if program_code == "PAGIBIG" and not has_caps:
            raise ValueError("Pag-IBIG brackets require employee and employer monthly contribution caps.")
        if program_code != "PAGIBIG" and (
            data.employee_contribution_cap is not None
            or data.employer_contribution_cap is not None
        ):
            raise ValueError("Contribution caps are only valid for Pag-IBIG brackets.")

    @staticmethod
    def _validate_tax_schedule(data: WithholdingTaxScheduleInput) -> None:
        validate_schedule_values(
            schedule_name=data.schedule_name,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
            source_reference=data.source_reference,
        )
        if data.tax_exempt_benefit_limit < Decimal(0):
            raise ValueError("tax_exempt_benefit_limit cannot be negative.")
        if data.calculation_basis not in {"ANNUAL_YTD", "SEMI_MONTHLY"}:
            raise ValueError("Unsupported withholding-tax calculation basis.")

    @staticmethod
    def _validate_tax_bracket(data: WithholdingTaxBracketInput) -> None:
        validate_withholding_tax_bracket_values(
            bracket_number=data.bracket_number,
            annual_income_min=data.annual_income_min,
            annual_income_max=data.annual_income_max,
            base_tax=data.base_tax,
            marginal_rate=data.marginal_rate,
            excess_over=data.excess_over,
        )
