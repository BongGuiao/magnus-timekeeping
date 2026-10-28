from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.location.domain.entities.location_type import LocationTypeEntity
from app.filemaintenance.location.infrastructure.db_model import Location  # noqa: F401
from app.filemaintenance.location.infrastructure.location_type_db_model import LocationType

DEFAULT_LOCATION_TYPES = (
    ("OFFICE", "Office", 10, True),
    ("WAREHOUSE", "Warehouse", 20, False),
    ("DISPATCH", "Dispatch", 30, False),
    ("CUSTOMER", "Customer", 40, False),
    ("FIELD", "Field", 50, False),
    ("FLEET_YARD", "Fleet yard", 60, False),
    ("OTHER", "Other", 70, False),
)


async def _ensure_default_location_types(uow: GenUnitOfWork, company_id: UUID) -> None:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    existing_type = await uow.session.scalar(
        select(LocationType.location_type)
        .where(LocationType.company_id == company_id)
        .limit(1)
    )
    if existing_type is not None:
        return
    await uow.session.execute(
        insert(LocationType)
        .values([
            {
                "company_id": company_id,
                "location_type": code,
                "display_name": label,
                "sort_order": sort_order,
                "is_default": is_default,
                "is_active": True,
            }
            for code, label, sort_order, is_default in DEFAULT_LOCATION_TYPES
        ])
        .on_conflict_do_nothing(index_elements=["company_id", "location_type"])
    )


class ListLocationTypesUseCase(BaseUseCase[list[LocationTypeEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID,
        include_inactive: bool = False,
        include_deleted: bool = False,
    ) -> list[LocationTypeEntity]:
        async with self.uow as uow:
            await _ensure_default_location_types(uow, company_id)
            repo = uow.get_repo(LocationTypeEntity, LocationType)
            criteria = [LocationType.company_id == company_id]
            if not include_inactive:
                criteria.append(LocationType.is_active.is_(True))
            if not include_deleted:
                criteria.append(LocationType.deleted_at.is_(None))
            return await repo.find_all(
                *criteria,
                order_by=LocationType.sort_order,
                offset=0,
                limit=100,
            )


class GetLocationTypeUseCase(BaseUseCase[LocationTypeEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID,
        location_type: str,
    ) -> LocationTypeEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(LocationTypeEntity, LocationType)
            return await repo.find_one(
                LocationType.company_id == company_id,
                LocationType.location_type == location_type,
            )


class LocationTypeConflictError(ValueError):
    pass


class CreateLocationTypeUseCase(BaseUseCase[LocationTypeEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> LocationTypeEntity:
        try:
            async with self.uow as uow:
                if uow.session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                existing = await uow.session.scalar(
                    select(LocationType.location_type).where(
                        LocationType.company_id == payload["company_id"],
                        LocationType.location_type == payload["location_type"],
                    )
                )
                if existing is not None:
                    raise LocationTypeConflictError(
                        f"Location type '{payload['location_type']}' already exists."
                    )
                if payload["is_default"]:
                    await uow.session.execute(
                        update(LocationType)
                        .where(LocationType.company_id == payload["company_id"])
                        .values(is_default=False)
                    )
                repo = uow.get_repo(LocationTypeEntity, LocationType)
                return await repo.add(payload)
        except IntegrityError as error:
            raise LocationTypeConflictError(
                "The location type could not be created because its code or default status conflicts with an existing type."
            ) from error


class UpdateLocationTypeUseCase(BaseUseCase[LocationTypeEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID,
        location_type: str,
        payload: dict[str, Any],
    ) -> LocationTypeEntity | None:
        try:
            async with self.uow as uow:
                if uow.session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                repo = uow.get_repo(LocationTypeEntity, LocationType)
                existing = await repo.find_one(
                    LocationType.company_id == company_id,
                    LocationType.location_type == location_type,
                )
                if existing is None:
                    return None
                if existing.deleted_at is not None:
                    raise ValueError("Deleted location types cannot be edited.")
                if payload["is_default"]:
                    await uow.session.execute(
                        update(LocationType)
                        .where(
                            LocationType.company_id == company_id,
                            LocationType.location_type != location_type,
                        )
                        .values(is_default=False)
                    )
                updated = replace(existing, **payload)
                return await repo.update(updated)
        except IntegrityError as error:
            raise LocationTypeConflictError(
                "The location type could not be updated because its default status conflicts with another type."
            ) from error


class DeleteLocationTypeUseCase(BaseUseCase[LocationTypeEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID,
        location_type: str,
        actor_id: UUID,
    ) -> LocationTypeEntity:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            location_type_model = (
                await uow.session.execute(
                    select(LocationType)
                    .where(
                        LocationType.company_id == company_id,
                        LocationType.location_type == location_type,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if location_type_model is None:
                raise ValueError(f"Location type '{location_type}' not found.")
            if location_type_model.deleted_at is not None:
                raise ValueError("This location type is already deleted.")

            now = datetime.now(timezone.utc)
            location_type_model.is_active = False
            location_type_model.is_default = False
            location_type_model.deleted_at = now
            location_type_model.deleted_by = actor_id
            await uow.session.flush()
            repo = uow.get_repo(LocationTypeEntity, LocationType)
            deleted = await repo.find_one(
                LocationType.company_id == company_id,
                LocationType.location_type == location_type,
            )
            if deleted is None:
                raise RuntimeError("Deleted location type could not be reloaded.")
            return deleted
