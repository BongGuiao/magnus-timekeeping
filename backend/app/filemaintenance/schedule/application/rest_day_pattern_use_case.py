from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.schedule.domain.entities.rest_day_pattern import (
    RestDayPatternDayEntity,
    RestDayPatternEntity,
)
from app.filemaintenance.schedule.infrastructure.db_model import (
    RestDayPatternDayModel,
    RestDayPatternModel,
)


class RestDayPatternConflictError(ValueError):
    pass


class RestDayPatternReferenceError(ValueError):
    pass


class RestDayPatternValidationError(ValueError):
    pass


def validate_pattern_days(cycle_length_days: int, days: list[dict[str, Any]]) -> None:
    cycle_day_numbers = [day["cycle_day_no"] for day in days]
    expected_days = set(range(1, cycle_length_days + 1))
    if len(cycle_day_numbers) != cycle_length_days or set(cycle_day_numbers) != expected_days:
        raise RestDayPatternValidationError(
            "Provide exactly one day for every cycle_day_no from 1 through cycle_length_days."
        )


def _translate_integrity_error(error: IntegrityError) -> NoReturn:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint_name in (
        "uq_rest_day_patterns_pattern_code",
        "rest_day_patterns_pattern_code_key",
    ):
        raise RestDayPatternConflictError(
            "A rest day pattern with this code already exists."
        ) from error
    if constraint_name in (
        "rest_day_pattern_days_schedule_template_id_fkey",
    ):
        raise RestDayPatternReferenceError("A schedule template assigned to a pattern day does not exist.") from error
    raise error


def _to_entity(
    pattern: RestDayPatternModel,
    days: list[RestDayPatternDayModel],
) -> RestDayPatternEntity:
    return RestDayPatternEntity(
        id=pattern.id,
        pattern_code=pattern.pattern_code,
        pattern_name=pattern.pattern_name,
        cycle_length_days=pattern.cycle_length_days,
        description=pattern.description,
        is_active=pattern.is_active,
        days=[
            RestDayPatternDayEntity(
                pattern_id=day.pattern_id,
                cycle_day_no=day.cycle_day_no,
                is_workday=day.is_workday,
                schedule_template_id=day.schedule_template_id,
            )
            for day in days
        ],
    )


def _new_day_models(
    pattern_id: UUID,
    days: list[dict[str, Any]],
) -> list[RestDayPatternDayModel]:
    return [
        RestDayPatternDayModel(pattern_id=pattern_id, **day)
        for day in days
    ]


class CreateRestDayPatternUseCase(BaseUseCase[RestDayPatternEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> RestDayPatternEntity:
        validate_pattern_days(payload["cycle_length_days"], payload["days"])
        days = payload["days"]
        pattern_values = {key: value for key, value in payload.items() if key != "days"}
        try:
            async with self.uow as uow:
                if uow.session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                pattern = RestDayPatternModel(**pattern_values)
                uow.session.add(pattern)
                await uow.session.flush()
                day_models = _new_day_models(pattern.id, days)
                uow.session.add_all(day_models)
                await uow.session.flush()
                return _to_entity(pattern, day_models)
        except IntegrityError as error:
            _translate_integrity_error(error)


class ListRestDayPatternsUseCase(BaseUseCase[list[RestDayPatternEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, is_active: bool | None = None) -> list[RestDayPatternEntity]:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            pattern_query = select(RestDayPatternModel).order_by(RestDayPatternModel.pattern_code)
            if is_active is not None:
                pattern_query = pattern_query.where(RestDayPatternModel.is_active.is_(is_active))
            patterns = list((await uow.session.scalars(pattern_query)).all())
            if not patterns:
                return []

            pattern_ids = [pattern.id for pattern in patterns]
            day_query = (
                select(RestDayPatternDayModel)
                .where(RestDayPatternDayModel.pattern_id.in_(pattern_ids))
                .order_by(RestDayPatternDayModel.pattern_id, RestDayPatternDayModel.cycle_day_no)
            )
            day_rows = list((await uow.session.scalars(day_query)).all())
            days_by_pattern: dict[UUID, list[RestDayPatternDayModel]] = {
                pattern_id: [] for pattern_id in pattern_ids
            }
            for day in day_rows:
                days_by_pattern[day.pattern_id].append(day)
            return [
                _to_entity(pattern, days_by_pattern[pattern.id])
                for pattern in patterns
            ]


class GetRestDayPatternUseCase(BaseUseCase[RestDayPatternEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, pattern_id: UUID) -> RestDayPatternEntity | None:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            pattern = await uow.session.get(RestDayPatternModel, pattern_id)
            if pattern is None:
                return None
            day_query = (
                select(RestDayPatternDayModel)
                .where(RestDayPatternDayModel.pattern_id == pattern_id)
                .order_by(RestDayPatternDayModel.cycle_day_no)
            )
            days = list((await uow.session.scalars(day_query)).all())
            return _to_entity(pattern, days)


class UpdateRestDayPatternUseCase(BaseUseCase[RestDayPatternEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        pattern_id: UUID,
        payload: dict[str, Any],
    ) -> RestDayPatternEntity | None:
        validate_pattern_days(payload["cycle_length_days"], payload["days"])
        days = payload["days"]
        pattern_values = {key: value for key, value in payload.items() if key != "days"}
        try:
            async with self.uow as uow:
                if uow.session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                pattern = await uow.session.get(RestDayPatternModel, pattern_id)
                if pattern is None:
                    return None
                for key, value in pattern_values.items():
                    setattr(pattern, key, value)
                await uow.session.execute(
                    delete(RestDayPatternDayModel).where(
                        RestDayPatternDayModel.pattern_id == pattern_id
                    )
                )
                day_models = _new_day_models(pattern_id, days)
                uow.session.add_all(day_models)
                await uow.session.flush()
                return _to_entity(pattern, day_models)
        except IntegrityError as error:
            _translate_integrity_error(error)


class DeleteRestDayPatternUseCase(BaseUseCase[RestDayPatternEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, pattern_id: UUID) -> RestDayPatternEntity | None:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            pattern = await uow.session.get(RestDayPatternModel, pattern_id)
            if pattern is None:
                return None
            day_query = (
                select(RestDayPatternDayModel)
                .where(RestDayPatternDayModel.pattern_id == pattern_id)
                .order_by(RestDayPatternDayModel.cycle_day_no)
            )
            days = list((await uow.session.scalars(day_query)).all())
            result = _to_entity(pattern, days)
            await uow.session.delete(pattern)
            await uow.session.flush()
            return result
