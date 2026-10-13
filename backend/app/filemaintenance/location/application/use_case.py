from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.location.domain.entities.location import LocationEntity
from app.filemaintenance.location.infrastructure.db_model import Location


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


class CreateLocationUseCase(BaseUseCase[LocationEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> LocationEntity:
        async with self.uow as uow:
            repo = uow.get_repo(LocationEntity, Location)
            created = await repo.add(_normalize_payload(payload))
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
