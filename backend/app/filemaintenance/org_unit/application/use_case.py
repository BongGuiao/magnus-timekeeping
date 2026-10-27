from dataclasses import replace
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.org_unit.domain.entities.org_unit import OrgUnitEntity
from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit
from app.filemaintenance.org_unit.domain.entities.org_unit_type import OrgUnitTypeEntity
from app.filemaintenance.org_unit.infrastructure.org_unit_type_db_model import OrgUnitType


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized_payload = payload.copy()
    for field in ("effective_from", "effective_to"):
        value = normalized_payload.get(field)
        if isinstance(value, str):
            normalized_payload[field] = date.fromisoformat(value)

    for field in (
        "company_id",
        "parent_org_unit_id",
        "manager_employee_id",
        "created_by",
        "updated_by",
        "id",
    ):
        value = normalized_payload.get(field)
        if isinstance(value, str):
            normalized_payload[field] = UUID(value)

    return normalized_payload


class CreateOrgUnitUseCase(BaseUseCase[OrgUnitEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> OrgUnitEntity:
        async with self.uow as uow:
            repo = uow.get_repo(OrgUnitEntity, OrgUnit)
            return await repo.add(_normalize_payload(payload))


class GetOrgUnitUseCase(BaseUseCase[OrgUnitEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, org_unit_id: UUID) -> OrgUnitEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(OrgUnitEntity, OrgUnit)
            return await repo.find_one(OrgUnit.id == org_unit_id)


class ListOrgUnitsUseCase(BaseUseCase[list[OrgUnitEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, company_id: UUID | None = None) -> list[OrgUnitEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(OrgUnitEntity, OrgUnit)
            criteria = [OrgUnit.company_id == company_id] if company_id is not None else []
            return await repo.find_all(
                *criteria,
                order_by=OrgUnit.org_unit_code,
                offset=0,
                limit=1000,
            )


class ListOrgUnitTypesUseCase(BaseUseCase[list[OrgUnitTypeEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, company_id: UUID) -> list[OrgUnitTypeEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(OrgUnitTypeEntity, OrgUnitType)
            return await repo.find_all(
                OrgUnitType.company_id == company_id,
                OrgUnitType.is_active.is_(True),
                order_by=OrgUnitType.sort_order,
                offset=0,
                limit=100,
            )


class GetOrgUnitTypeUseCase(BaseUseCase[OrgUnitTypeEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID,
        org_unit_type: str,
    ) -> OrgUnitTypeEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(OrgUnitTypeEntity, OrgUnitType)
            return await repo.find_one(
                OrgUnitType.company_id == company_id,
                OrgUnitType.org_unit_type == org_unit_type,
            )


class OrgUnitTypeConflictError(ValueError):
    pass


class CreateOrgUnitTypeUseCase(BaseUseCase[OrgUnitTypeEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> OrgUnitTypeEntity:
        try:
            async with self.uow as uow:
                if uow.session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                existing = await uow.session.scalar(
                    select(OrgUnitType.org_unit_type).where(
                        OrgUnitType.company_id == payload["company_id"],
                        OrgUnitType.org_unit_type == payload["org_unit_type"]
                    )
                )
                if existing is not None:
                    raise OrgUnitTypeConflictError(
                        f"Organization unit type '{payload['org_unit_type']}' already exists."
                    )
                if payload["is_default"]:
                    await uow.session.execute(
                        update(OrgUnitType)
                        .where(OrgUnitType.company_id == payload["company_id"])
                        .values(is_default=False)
                    )
                repo = uow.get_repo(OrgUnitTypeEntity, OrgUnitType)
                return await repo.add(payload)
        except IntegrityError as error:
            raise OrgUnitTypeConflictError(
                "The organization unit type could not be created because its code or default status conflicts with an existing type."
            ) from error


class UpdateOrgUnitTypeUseCase(BaseUseCase[OrgUnitTypeEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID,
        org_unit_type: str,
        payload: dict[str, Any],
    ) -> OrgUnitTypeEntity | None:
        try:
            async with self.uow as uow:
                if uow.session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                repo = uow.get_repo(OrgUnitTypeEntity, OrgUnitType)
                existing = await repo.find_one(
                    OrgUnitType.company_id == company_id,
                    OrgUnitType.org_unit_type == org_unit_type
                )
                if existing is None:
                    return None
                if payload["is_default"]:
                    await uow.session.execute(
                        update(OrgUnitType)
                        .where(
                            OrgUnitType.company_id == company_id,
                            OrgUnitType.org_unit_type != org_unit_type,
                        )
                        .values(is_default=False)
                    )
                updated = replace(existing, **payload)
                return await repo.update(updated)
        except IntegrityError as error:
            raise OrgUnitTypeConflictError(
                "The organization unit type could not be updated because its default status conflicts with another type."
            ) from error


class UpdateOrgUnitUseCase(BaseUseCase[OrgUnitEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, org_unit_id: UUID, payload: dict[str, Any]) -> OrgUnitEntity:
        async with self.uow as uow:
            repo = uow.get_repo(OrgUnitEntity, OrgUnit)
            existing = await repo.find_one(OrgUnit.id == org_unit_id)
            if existing is None:
                raise ValueError("Org unit not found.")

            entity_data = GenericMapper.to_entity(_normalize_payload(payload), OrgUnitEntity)
            entity_data.id = org_unit_id
            changes = {
                key: value for key, value in entity_data.__dict__.items()
                if key not in ("id", "created_at", "created_by", "row_version", "updated_at", "updated_by")
            }
            updated = replace(
                existing,
                **changes,
                updated_at=entity_data.updated_at or existing.updated_at,
                updated_by=entity_data.updated_by or existing.updated_by,
                row_version=(existing.row_version or 0) + 1,
            )
            return await repo.update(updated)
