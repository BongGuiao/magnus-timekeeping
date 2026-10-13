from dataclasses import replace
from typing import Any
from uuid import UUID

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.holidays.calendar.domain.entities.holiday_calendar import (
    HolidayCalendarEntity,
)
from app.filemaintenance.holidays.calendar.infrastructure.db_model import (
    HolidayCalendarModel,
)


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = payload.copy()
    for field in ("company_id", "created_by", "updated_by", "id"):
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = UUID(value)
    return normalized


class CreateHolidayCalendarUseCase(BaseUseCase[HolidayCalendarEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> HolidayCalendarEntity:
        async with self.uow as uow:
            repo = uow.get_repo(HolidayCalendarEntity, HolidayCalendarModel)
            return await repo.add(_normalize_payload(payload))


class GetHolidayCalendarUseCase(BaseUseCase[HolidayCalendarEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, calendar_id: UUID) -> HolidayCalendarEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(HolidayCalendarEntity, HolidayCalendarModel)
            return await repo.find_one(HolidayCalendarModel.id == calendar_id)


class ListHolidayCalendarsUseCase(BaseUseCase[list[HolidayCalendarEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID | None = None,
        effective_year: int | None = None,
        calendar_status: str | None = None,
    ) -> list[HolidayCalendarEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(HolidayCalendarEntity, HolidayCalendarModel)
            criteria = []
            if company_id is not None:
                criteria.append(HolidayCalendarModel.company_id == company_id)
            if effective_year is not None:
                criteria.append(HolidayCalendarModel.effective_year == effective_year)
            if calendar_status is not None:
                criteria.append(HolidayCalendarModel.status == calendar_status)
            return await repo.find_all(
                *criteria,
                order_by=(
                    HolidayCalendarModel.effective_year.desc(),
                    HolidayCalendarModel.calendar_code,
                ),
                offset=0,
                limit=1000,
            )


class UpdateHolidayCalendarUseCase(BaseUseCase[HolidayCalendarEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        calendar_id: UUID,
        payload: dict[str, Any],
    ) -> HolidayCalendarEntity:
        async with self.uow as uow:
            repo = uow.get_repo(HolidayCalendarEntity, HolidayCalendarModel)
            existing = await repo.find_one(HolidayCalendarModel.id == calendar_id)
            if existing is None:
                raise ValueError("Holiday calendar not found.")

            merged_payload = {**existing.__dict__, **_normalize_payload(payload)}
            entity_data = GenericMapper.to_entity(merged_payload, HolidayCalendarEntity)
            entity_data.id = calendar_id
            changes = {
                key: value
                for key, value in entity_data.__dict__.items()
                if key not in (
                    "id",
                    "created_at",
                    "created_by",
                    "row_version",
                    "updated_at",
                    "updated_by",
                )
            }
            updated = replace(
                existing,
                **changes,
                updated_at=entity_data.updated_at or existing.updated_at,
                updated_by=entity_data.updated_by or existing.updated_by,
                row_version=(existing.row_version or 0) + 1,
            )
            return await repo.update(updated)
