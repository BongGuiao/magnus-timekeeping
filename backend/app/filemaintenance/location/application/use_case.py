from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.location.domain.entities.location import LocationEntity
from app.filemaintenance.location.infrastructure.db_model import Location

NCR_PSGC_REGION_CODE = "130000000"
NCR_REGION_NAMES = {"NCR", "NATIONAL CAPITAL REGION"}
NCR_DISTRICTS = {
    "NCR_1ST_DISTRICT",
    "NCR_2ND_DISTRICT",
    "NCR_3RD_DISTRICT",
    "NCR_4TH_DISTRICT",
}


async def _include_geo_point_wkt(
    uow: GenUnitOfWork,
    locations: list[LocationEntity],
) -> list[LocationEntity]:
    if not locations:
        return locations
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")

    location_ids = [location.id for location in locations if location.id is not None]
    result = await uow.session.execute(
        select(Location.id, func.ST_AsText(Location.geo_point)).where(Location.id.in_(location_ids))
    )
    geo_points = {location_id: geo_point for location_id, geo_point in result}
    for location in locations:
        location.geo_point = geo_points.get(location.id)
    return locations


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = payload.copy()
    for field in ("company_id", "created_by", "updated_by", "id"):
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = UUID(value)
    return normalized


def _validate_ncr_district(location: LocationEntity) -> None:
    is_ncr = (
        location.psgc_region_code == NCR_PSGC_REGION_CODE
        if location.psgc_region_code
        else (location.region or "").strip().upper() in NCR_REGION_NAMES
    )
    if location.ncr_district and (
        location.ncr_district not in NCR_DISTRICTS or not is_ncr
    ):
        raise ValueError("An NCR district can only be assigned to an NCR location.")
    if is_ncr and not location.ncr_district:
        raise ValueError("Select an NCR district for this location.")


class CreateLocationUseCase(BaseUseCase[LocationEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> LocationEntity:
        async with self.uow as uow:
            normalized = _normalize_payload(payload)
            entity = GenericMapper.to_entity(normalized, LocationEntity)
            if entity is None:
                raise ValueError("Location details are required.")
            _validate_ncr_district(entity)
            repo = uow.get_repo(LocationEntity, Location)
            created = await repo.add(normalized)
            return (await _include_geo_point_wkt(uow, [created]))[0]


class GetLocationUseCase(BaseUseCase[LocationEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, location_id: UUID) -> LocationEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(LocationEntity, Location)
            location = await repo.find_one(Location.id == location_id)
            if location is None:
                return None
            return (await _include_geo_point_wkt(uow, [location]))[0]


class ListLocationsUseCase(BaseUseCase[list[LocationEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, company_id: UUID | None = None) -> list[LocationEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(LocationEntity, Location)
            criteria = (Location.company_id == company_id,) if company_id else ()
            locations = await repo.find_all(
                *criteria,
                order_by=Location.location_code,
                offset=0,
                limit=1000,
            )
            return await _include_geo_point_wkt(uow, locations)


class UpdateLocationUseCase(BaseUseCase[LocationEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, location_id: UUID, payload: dict[str, Any]) -> LocationEntity:
        async with self.uow as uow:
            repo = uow.get_repo(LocationEntity, Location)
            existing = await repo.find_one(Location.id == location_id)
            if existing is None:
                raise ValueError("Location not found.")

            existing = (await _include_geo_point_wkt(uow, [existing]))[0]
            normalized = _normalize_payload(payload)
            entity_data = GenericMapper.to_entity(
                {**existing.__dict__, **normalized},
                LocationEntity,
            )
            if entity_data is None:
                raise ValueError("Location details are required.")
            _validate_ncr_district(entity_data)
            entity_data.id = location_id
            changes = {
                key: value
                for key, value in entity_data.__dict__.items()
                if key not in ("id", "created_at", "created_by", "row_version", "updated_at", "updated_by")
            }
            updated = replace(
                existing,
                **changes,
                updated_at=entity_data.updated_at or existing.updated_at,
                updated_by=entity_data.updated_by or existing.updated_by,
                row_version=(existing.row_version or 0) + 1,
            )
            saved = await repo.update(updated)
            return (await _include_geo_point_wkt(uow, [saved]))[0]
