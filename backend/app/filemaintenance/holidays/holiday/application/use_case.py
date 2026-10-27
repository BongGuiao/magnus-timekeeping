from dataclasses import replace
from datetime import date
from typing import Any
from uuid import UUID

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.holidays.holiday.domain.entities.holiday import HolidayEntity
from app.filemaintenance.holidays.holiday.infrastructure.db_model import HolidayModel

NCR_PSGC_REGION_CODE = "130000000"
NCR_REGION_NAMES = {"NCR", "NATIONAL CAPITAL REGION"}
NCR_DISTRICTS = {
    "NCR_1ST_DISTRICT",
    "NCR_2ND_DISTRICT",
    "NCR_3RD_DISTRICT",
    "NCR_4TH_DISTRICT",
}


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


async def _validate_local_holiday_scope(
    holiday: HolidayEntity,
) -> None:
    if holiday.holiday_type != "LOCAL":
        return
    has_region = bool(holiday.psgc_region_code or holiday.region)
    is_ncr = (
        holiday.psgc_region_code == NCR_PSGC_REGION_CODE
        if holiday.psgc_region_code
        else (holiday.region or "").strip().upper() in NCR_REGION_NAMES
    )
    if holiday.ncr_district and (
        holiday.ncr_district not in NCR_DISTRICTS or not is_ncr
    ):
        raise ValueError("An NCR district can only be used with an NCR local holiday.")
    if not has_region or not (
        holiday.psgc_province_code or holiday.province or holiday.ncr_district
    ):
        raise ValueError(
            "A local holiday must specify a region and either a province or NCR district; municipality is optional."
        )


class CreateHolidayUseCase(BaseUseCase[HolidayEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> HolidayEntity:
        async with self.uow as uow:
            normalized = _normalize_payload(payload)
            holiday = GenericMapper.to_entity(normalized, HolidayEntity)
            if holiday is None:
                raise ValueError("Holiday details are required.")
            await _validate_local_holiday_scope(holiday)
            repo = uow.get_repo(HolidayEntity, HolidayModel)
            return await repo.add(normalized)


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
            if entity_data is None:
                raise ValueError("Holiday details are required.")
            entity_data.id = holiday_id
            await _validate_local_holiday_scope(entity_data)
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
