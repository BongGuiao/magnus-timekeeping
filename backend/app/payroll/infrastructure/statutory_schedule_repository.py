from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import wraps
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.generics.uow import GenUnitOfWork
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
    validate_complete_bracket_ranges,
)
from app.payroll.infrastructure.db_model import (
    StatutoryContributionBracketModel,
    StatutoryContributionScheduleModel,
    WithholdingTaxBracketModel,
    WithholdingTaxScheduleModel,
)

P = ParamSpec("P")
R = TypeVar("R")


def _translate_integrity_errors(
    operation: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    @wraps(operation)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await operation(*args, **kwargs)
        except IntegrityError as error:
            raise ValueError(
                "The schedule or bracket conflicts with an existing range or database constraint."
            ) from error

    return wrapped


def _contribution_schedule_entity(
    model: StatutoryContributionScheduleModel,
) -> ContributionSchedule:
    return ContributionSchedule(
        id=model.id,
        program_code=model.program_code,
        schedule_name=model.schedule_name,
        effective_from=model.effective_from,
        effective_to=model.effective_to,
        source_reference=model.source_reference,
        status=model.status,
        created_at=model.created_at,
        created_by=model.created_by,
        updated_at=model.updated_at,
        updated_by=model.updated_by,
        row_version=model.row_version,
    )


def _contribution_bracket_entity(
    model: StatutoryContributionBracketModel,
) -> ContributionBracket:
    return ContributionBracket(
        id=model.id,
        schedule_id=model.schedule_id,
        bracket_number=model.bracket_number,
        compensation_min=Decimal(model.compensation_min),
        compensation_max=(
            Decimal(model.compensation_max) if model.compensation_max is not None else None
        ),
        contribution_base=Decimal(model.contribution_base),
        employee_rate=Decimal(model.employee_rate),
        employer_rate=Decimal(model.employer_rate),
        employee_fixed_amount=Decimal(model.employee_fixed_amount),
        employer_fixed_amount=Decimal(model.employer_fixed_amount),
        employer_additional_fixed_amount=Decimal(model.employer_additional_fixed_amount),
    )


def _tax_schedule_entity(model: WithholdingTaxScheduleModel) -> WithholdingTaxSchedule:
    return WithholdingTaxSchedule(
        id=model.id,
        schedule_name=model.schedule_name,
        effective_from=model.effective_from,
        effective_to=model.effective_to,
        tax_exempt_benefit_limit=Decimal(model.tax_exempt_benefit_limit),
        source_reference=model.source_reference,
        status=model.status,
        created_at=model.created_at,
        created_by=model.created_by,
        updated_at=model.updated_at,
        updated_by=model.updated_by,
        row_version=model.row_version,
    )


def _tax_bracket_entity(model: WithholdingTaxBracketModel) -> WithholdingTaxBracket:
    return WithholdingTaxBracket(
        id=model.id,
        schedule_id=model.schedule_id,
        bracket_number=model.bracket_number,
        annual_income_min=Decimal(model.annual_income_min),
        annual_income_max=(
            Decimal(model.annual_income_max) if model.annual_income_max is not None else None
        ),
        base_tax=Decimal(model.base_tax),
        marginal_rate=Decimal(model.marginal_rate),
        excess_over=Decimal(model.excess_over),
    )


class SqlAlchemyStatutoryScheduleRepository:
    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow

    async def list_contribution_schedules(
        self, program_code: ContributionProgram | None
    ) -> list[ContributionSchedule]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            query = select(StatutoryContributionScheduleModel)
            if program_code is not None:
                query = query.where(
                    StatutoryContributionScheduleModel.program_code == program_code
                )
            models = await session.scalars(
                query.order_by(
                    StatutoryContributionScheduleModel.program_code,
                    StatutoryContributionScheduleModel.effective_from.desc(),
                )
            )
            return [_contribution_schedule_entity(model) for model in models]

    async def get_contribution_schedule(self, schedule_id: UUID) -> ContributionSchedule:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.get(StatutoryContributionScheduleModel, schedule_id)
            if model is None:
                raise LookupError("Contribution schedule not found.")
            return _contribution_schedule_entity(model)

    @_translate_integrity_errors
    async def create_contribution_schedule(
        self,
        *,
        program_code: ContributionProgram,
        schedule_name: str,
        effective_from: date,
        effective_to: date | None,
        source_reference: str,
        actor_id: UUID,
    ) -> ContributionSchedule:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = StatutoryContributionScheduleModel(
                program_code=program_code,
                schedule_name=schedule_name,
                effective_from=effective_from,
                effective_to=effective_to,
                source_reference=source_reference,
                status="DRAFT",
                created_by=actor_id,
                updated_by=actor_id,
            )
            session.add(model)
            await session.flush()
            return _contribution_schedule_entity(model)

    @_translate_integrity_errors
    async def update_contribution_schedule(
        self,
        *,
        schedule_id: UUID,
        schedule_name: str,
        effective_from: date,
        effective_to: date | None,
        source_reference: str,
        actor_id: UUID,
    ) -> ContributionSchedule:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(StatutoryContributionScheduleModel)
                .where(StatutoryContributionScheduleModel.id == schedule_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Contribution schedule not found.")
            self._require_draft(model.status)
            model.schedule_name = schedule_name
            model.effective_from = effective_from
            model.effective_to = effective_to
            model.source_reference = source_reference
            self._stamp_update(model, actor_id)
            await session.flush()
            return _contribution_schedule_entity(model)

    @_translate_integrity_errors
    async def set_contribution_schedule_status(
        self, schedule_id: UUID, status: str, actor_id: UUID
    ) -> ContributionSchedule:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(StatutoryContributionScheduleModel)
                .where(StatutoryContributionScheduleModel.id == schedule_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Contribution schedule not found.")
            if status == "ACTIVE":
                if model.status != "DRAFT":
                    raise ValueError("Only draft schedules can be activated.")
                brackets = await session.scalars(
                    select(StatutoryContributionBracketModel)
                    .where(StatutoryContributionBracketModel.schedule_id == schedule_id)
                    .order_by(StatutoryContributionBracketModel.compensation_min)
                )
                validate_complete_bracket_ranges(
                    [
                        (
                            bracket.bracket_number,
                            Decimal(bracket.compensation_min),
                            (
                                Decimal(bracket.compensation_max)
                                if bracket.compensation_max is not None
                                else None
                            ),
                        )
                        for bracket in brackets
                    ]
                )
                overlap_query = select(StatutoryContributionScheduleModel.id).where(
                    StatutoryContributionScheduleModel.id != schedule_id,
                    StatutoryContributionScheduleModel.program_code == model.program_code,
                    StatutoryContributionScheduleModel.status == "ACTIVE",
                    or_(
                        StatutoryContributionScheduleModel.effective_to.is_(None),
                        StatutoryContributionScheduleModel.effective_to >= model.effective_from,
                    ),
                )
                if model.effective_to is not None:
                    overlap_query = overlap_query.where(
                        StatutoryContributionScheduleModel.effective_from <= model.effective_to
                    )
                active_overlap = await session.scalar(overlap_query.limit(1))
                if active_overlap is not None:
                    raise ValueError(
                        "An active schedule for this program already covers these dates."
                    )
            elif status == "RETIRED" and model.status != "ACTIVE":
                raise ValueError("Only active contribution schedules can be retired.")
            model.status = status
            self._stamp_update(model, actor_id)
            await session.flush()
            return _contribution_schedule_entity(model)

    @_translate_integrity_errors
    async def delete_contribution_schedule(self, schedule_id: UUID) -> None:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(StatutoryContributionScheduleModel)
                .where(StatutoryContributionScheduleModel.id == schedule_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Contribution schedule not found.")
            self._require_draft(model.status)
            await session.delete(model)

    async def list_contribution_brackets(self, schedule_id: UUID) -> list[ContributionBracket]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            models = await session.scalars(
                select(StatutoryContributionBracketModel)
                .where(StatutoryContributionBracketModel.schedule_id == schedule_id)
                .order_by(StatutoryContributionBracketModel.compensation_min)
            )
            return [_contribution_bracket_entity(model) for model in models]

    async def get_contribution_bracket(self, bracket_id: UUID) -> ContributionBracket:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.get(StatutoryContributionBracketModel, bracket_id)
            if model is None:
                raise LookupError("Contribution bracket not found.")
            return _contribution_bracket_entity(model)

    @_translate_integrity_errors
    async def create_contribution_bracket(
        self, *, schedule_id: UUID, values: ContributionBracketInput
    ) -> ContributionBracket:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            await self._lock_draft_contribution_schedule(session, schedule_id)
            model = StatutoryContributionBracketModel(
                schedule_id=schedule_id, **asdict(values)
            )
            session.add(model)
            await session.flush()
            return _contribution_bracket_entity(model)

    @_translate_integrity_errors
    async def update_contribution_bracket(
        self, bracket_id: UUID, values: ContributionBracketInput
    ) -> ContributionBracket:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(StatutoryContributionBracketModel)
                .where(StatutoryContributionBracketModel.id == bracket_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Contribution bracket not found.")
            await self._lock_draft_contribution_schedule(session, model.schedule_id)
            for name, value in asdict(values).items():
                setattr(model, name, value)
            await session.flush()
            return _contribution_bracket_entity(model)

    @_translate_integrity_errors
    async def delete_contribution_bracket(self, bracket_id: UUID) -> None:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(StatutoryContributionBracketModel)
                .where(StatutoryContributionBracketModel.id == bracket_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Contribution bracket not found.")
            await self._lock_draft_contribution_schedule(session, model.schedule_id)
            await session.delete(model)

    async def list_withholding_tax_schedules(self) -> list[WithholdingTaxSchedule]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            models = await session.scalars(
                select(WithholdingTaxScheduleModel).order_by(
                    WithholdingTaxScheduleModel.effective_from.desc()
                )
            )
            return [_tax_schedule_entity(model) for model in models]

    async def get_withholding_tax_schedule(self, schedule_id: UUID) -> WithholdingTaxSchedule:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.get(WithholdingTaxScheduleModel, schedule_id)
            if model is None:
                raise LookupError("Withholding tax schedule not found.")
            return _tax_schedule_entity(model)

    @_translate_integrity_errors
    async def create_withholding_tax_schedule(
        self,
        *,
        schedule_name: str,
        effective_from: date,
        effective_to: date | None,
        tax_exempt_benefit_limit: Decimal,
        source_reference: str,
        actor_id: UUID,
    ) -> WithholdingTaxSchedule:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = WithholdingTaxScheduleModel(
                schedule_name=schedule_name,
                effective_from=effective_from,
                effective_to=effective_to,
                tax_exempt_benefit_limit=tax_exempt_benefit_limit,
                source_reference=source_reference,
                status="DRAFT",
                created_by=actor_id,
                updated_by=actor_id,
            )
            session.add(model)
            await session.flush()
            return _tax_schedule_entity(model)

    @_translate_integrity_errors
    async def update_withholding_tax_schedule(
        self,
        *,
        schedule_id: UUID,
        schedule_name: str,
        effective_from: date,
        effective_to: date | None,
        tax_exempt_benefit_limit: Decimal,
        source_reference: str,
        actor_id: UUID,
    ) -> WithholdingTaxSchedule:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(WithholdingTaxScheduleModel)
                .where(WithholdingTaxScheduleModel.id == schedule_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Withholding tax schedule not found.")
            self._require_draft(model.status)
            model.schedule_name = schedule_name
            model.effective_from = effective_from
            model.effective_to = effective_to
            model.tax_exempt_benefit_limit = tax_exempt_benefit_limit
            model.source_reference = source_reference
            self._stamp_update(model, actor_id)
            await session.flush()
            return _tax_schedule_entity(model)

    @_translate_integrity_errors
    async def set_withholding_tax_schedule_status(
        self, schedule_id: UUID, status: str, actor_id: UUID
    ) -> WithholdingTaxSchedule:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(WithholdingTaxScheduleModel)
                .where(WithholdingTaxScheduleModel.id == schedule_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Withholding tax schedule not found.")
            if status == "ACTIVE":
                if model.status != "DRAFT":
                    raise ValueError("Only draft schedules can be activated.")
                brackets = await session.scalars(
                    select(WithholdingTaxBracketModel)
                    .where(WithholdingTaxBracketModel.schedule_id == schedule_id)
                    .order_by(WithholdingTaxBracketModel.annual_income_min)
                )
                validate_complete_bracket_ranges(
                    [
                        (
                            bracket.bracket_number,
                            Decimal(bracket.annual_income_min),
                            (
                                Decimal(bracket.annual_income_max)
                                if bracket.annual_income_max is not None
                                else None
                            ),
                        )
                        for bracket in brackets
                    ]
                )
                overlap_query = select(WithholdingTaxScheduleModel.id).where(
                    WithholdingTaxScheduleModel.id != schedule_id,
                    WithholdingTaxScheduleModel.status == "ACTIVE",
                    or_(
                        WithholdingTaxScheduleModel.effective_to.is_(None),
                        WithholdingTaxScheduleModel.effective_to >= model.effective_from,
                    ),
                )
                if model.effective_to is not None:
                    overlap_query = overlap_query.where(
                        WithholdingTaxScheduleModel.effective_from <= model.effective_to
                    )
                active_overlap = await session.scalar(overlap_query.limit(1))
                if active_overlap is not None:
                    raise ValueError(
                        "An active withholding tax schedule already covers these dates."
                    )
            elif status == "RETIRED" and model.status != "ACTIVE":
                raise ValueError("Only active withholding tax schedules can be retired.")
            model.status = status
            self._stamp_update(model, actor_id)
            await session.flush()
            return _tax_schedule_entity(model)

    @_translate_integrity_errors
    async def delete_withholding_tax_schedule(self, schedule_id: UUID) -> None:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(WithholdingTaxScheduleModel)
                .where(WithholdingTaxScheduleModel.id == schedule_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Withholding tax schedule not found.")
            self._require_draft(model.status)
            await session.delete(model)

    async def list_withholding_tax_brackets(
        self, schedule_id: UUID
    ) -> list[WithholdingTaxBracket]:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            models = await session.scalars(
                select(WithholdingTaxBracketModel)
                .where(WithholdingTaxBracketModel.schedule_id == schedule_id)
                .order_by(WithholdingTaxBracketModel.annual_income_min)
            )
            return [_tax_bracket_entity(model) for model in models]

    async def get_withholding_tax_bracket(self, bracket_id: UUID) -> WithholdingTaxBracket:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.get(WithholdingTaxBracketModel, bracket_id)
            if model is None:
                raise LookupError("Withholding tax bracket not found.")
            return _tax_bracket_entity(model)

    @_translate_integrity_errors
    async def create_withholding_tax_bracket(
        self, *, schedule_id: UUID, values: WithholdingTaxBracketInput
    ) -> WithholdingTaxBracket:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            await self._lock_draft_tax_schedule(session, schedule_id)
            model = WithholdingTaxBracketModel(schedule_id=schedule_id, **asdict(values))
            session.add(model)
            await session.flush()
            return _tax_bracket_entity(model)

    @_translate_integrity_errors
    async def update_withholding_tax_bracket(
        self, bracket_id: UUID, values: WithholdingTaxBracketInput
    ) -> WithholdingTaxBracket:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(WithholdingTaxBracketModel)
                .where(WithholdingTaxBracketModel.id == bracket_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Withholding tax bracket not found.")
            await self._lock_draft_tax_schedule(session, model.schedule_id)
            for name, value in asdict(values).items():
                setattr(model, name, value)
            await session.flush()
            return _tax_bracket_entity(model)

    @_translate_integrity_errors
    async def delete_withholding_tax_bracket(self, bracket_id: UUID) -> None:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            model = await session.scalar(
                select(WithholdingTaxBracketModel)
                .where(WithholdingTaxBracketModel.id == bracket_id)
                .with_for_update()
            )
            if model is None:
                raise LookupError("Withholding tax bracket not found.")
            await self._lock_draft_tax_schedule(session, model.schedule_id)
            await session.delete(model)

    @staticmethod
    def _require_draft(status: str) -> None:
        if status != "DRAFT":
            raise ValueError("Only draft schedules can be edited or deleted.")

    async def _lock_draft_contribution_schedule(
        self, session: AsyncSession, schedule_id: UUID
    ) -> None:
        model = await session.scalar(
            select(StatutoryContributionScheduleModel)
            .where(StatutoryContributionScheduleModel.id == schedule_id)
            .with_for_update()
        )
        if model is None:
            raise LookupError("Contribution schedule not found.")
        self._require_draft(model.status)

    async def _lock_draft_tax_schedule(
        self, session: AsyncSession, schedule_id: UUID
    ) -> None:
        model = await session.scalar(
            select(WithholdingTaxScheduleModel)
            .where(WithholdingTaxScheduleModel.id == schedule_id)
            .with_for_update()
        )
        if model is None:
            raise LookupError("Withholding tax schedule not found.")
        self._require_draft(model.status)

    @staticmethod
    def _stamp_update(
        model: StatutoryContributionScheduleModel | WithholdingTaxScheduleModel,
        actor_id: UUID,
    ) -> None:
        model.updated_by = actor_id
        model.updated_at = datetime.now(timezone.utc)
        model.row_version += 1
