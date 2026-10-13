from dataclasses import replace
from datetime import date
from typing import Any
from uuid import UUID

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.holidays.holiday.domain.entities.holiday import HolidayEntity
from app.filemaintenance.holidays.holiday.infrastructure.db_model import HolidayModel


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = payload.copy()
    holiday_date = normalized.get("holiday_date")
    if isinstance(holiday_date, str):
        normalized["holiday_date"] = date.fromisoformat(holiday_date)

    for field in ("holiday_calendar_id", "created_by", "updated_by", "id"):
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = UUID(value)
    return normalized


class CreateHolidayUseCase(BaseUseCase[HolidayEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> HolidayEntity:
        async with self.uow as uow:
            repo = uow.get_repo(HolidayEntity, HolidayModel)
            return await repo.add(_normalize_payload(payload))


class GetHolidayUseCase(BaseUseCase[HolidayEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, holiday_id: UUID) -> HolidayEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(HolidayEntity, HolidayModel)
            return await repo.find_one(HolidayModel.id == holiday_id)


class ListHolidaysUseCase(BaseUseCase[list[HolidayEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        holiday_calendar_id: UUID | None = None,
        holiday_status: str | None = None,
    ) -> list[HolidayEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(HolidayEntity, HolidayModel)
            criteria = []
            if holiday_calendar_id is not None:
                criteria.append(HolidayModel.holiday_calendar_id == holiday_calendar_id)
            if holiday_status is not None:
                criteria.append(HolidayModel.status == holiday_status)
            return await repo.find_all(
                *criteria,
                order_by=(HolidayModel.holiday_date, HolidayModel.holiday_name),
                offset=0,
                limit=1000,
            )


class UpdateHolidayUseCase(BaseUseCase[HolidayEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, holiday_id: UUID, payload: dict[str, Any]) -> HolidayEntity:
        async with self.uow as uow:
            repo = uow.get_repo(HolidayEntity, HolidayModel)
            existing = await repo.find_one(HolidayModel.id == holiday_id)
            if existing is None:
                raise ValueError("Holiday not found.")

            merged_payload = {**existing.__dict__, **_normalize_payload(payload)}
            entity_data = GenericMapper.to_entity(merged_payload, HolidayEntity)
            entity_data.id = holiday_id
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
