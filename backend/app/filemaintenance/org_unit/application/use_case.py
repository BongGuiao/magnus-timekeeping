from dataclasses import replace
from datetime import date
from typing import Any
from uuid import UUID

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.org_unit.domain.entities.org_unit import OrgUnitEntity
from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit


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
