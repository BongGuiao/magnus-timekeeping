from datetime import datetime
from typing import Any
from uuid import UUID

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.geofences.domain.entities.geofence import GeofenceEntity
from app.filemaintenance.geofences.infrastructure.db_model import Geofence


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = payload.copy()
    for field in ("company_id", "location_id", "created_by", "updated_by", "id"):
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = UUID(value)

    for field in ("effective_from", "effective_to", "created_at", "updated_at"):
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = datetime.fromisoformat(value.replace("Z", "+00:00"))

    for field in ("center_point", "boundary_polygon"):
        value = normalized.get(field)
        if isinstance(value, str):
            value = value.strip()
            normalized[field] = WKTElement(value, srid=4326) if value else None

    return normalized


async def _get_geofence(
    uow: GenUnitOfWork,
    geofence_id: UUID,
) -> GeofenceEntity | None:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")

    result = await uow.session.execute(
        select(
            Geofence,
            func.ST_AsText(Geofence.center_point),
            func.ST_AsText(Geofence.boundary_polygon),
        ).where(Geofence.id == geofence_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    geofence = GenericMapper.to_entity(row[0], GeofenceEntity)
    geofence.center_point = row[1]
    geofence.boundary_polygon = row[2]
    return geofence


async def _list_geofences(
    uow: GenUnitOfWork,
    company_id: UUID | None,
) -> list[GeofenceEntity]:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")

    query = select(
        Geofence,
        func.ST_AsText(Geofence.center_point),
        func.ST_AsText(Geofence.boundary_polygon),
    )
    if company_id is not None:
        query = query.where(Geofence.company_id == company_id)
    result = await uow.session.execute(
        query.order_by(Geofence.geofence_code).limit(1000)
    )
    geofences: list[GeofenceEntity] = []
    for row in result:
        geofence = GenericMapper.to_entity(row[0], GeofenceEntity)
        geofence.center_point = row[1]
        geofence.boundary_polygon = row[2]
        geofences.append(geofence)
    return geofences


class CreateGeofenceUseCase(BaseUseCase[GeofenceEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> GeofenceEntity:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            geofence = Geofence(**_normalize_payload(payload))
            uow.session.add(geofence)
            await uow.session.flush()
            await uow.session.refresh(geofence)
            result = await _get_geofence(uow, geofence.id)
            if result is None:
                raise RuntimeError("Created geofence could not be reloaded.")
            return result


class GetGeofenceUseCase(BaseUseCase[GeofenceEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, geofence_id: UUID) -> GeofenceEntity | None:
        async with self.uow as uow:
            return await _get_geofence(uow, geofence_id)


class ListGeofencesUseCase(BaseUseCase[list[GeofenceEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, company_id: UUID | None = None) -> list[GeofenceEntity]:
        async with self.uow as uow:
            return await _list_geofences(uow, company_id)


class UpdateGeofenceUseCase(BaseUseCase[GeofenceEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, geofence_id: UUID, payload: dict[str, Any]) -> GeofenceEntity:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            result = await uow.session.execute(
                select(Geofence).where(Geofence.id == geofence_id)
            )
            geofence = result.scalar_one_or_none()
            if geofence is None:
                raise ValueError("Geofence not found.")

            updates = _normalize_payload(payload)
            for field, value in updates.items():
                if field not in {
                    "id",
                    "created_at",
                    "created_by",
                    "row_version",
                }:
                    setattr(geofence, field, value)
            geofence.row_version = (geofence.row_version or 0) + 1
            await uow.session.flush()
            await uow.session.refresh(geofence)
            updated = await _get_geofence(uow, geofence_id)
            if updated is None:
                raise RuntimeError("Updated geofence could not be reloaded.")
            return updated
