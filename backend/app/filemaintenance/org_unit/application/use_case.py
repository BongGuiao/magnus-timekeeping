from dataclasses import replace
from datetime import date, datetime, timezone
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
            normalized = _normalize_payload(payload)
            normalized.pop("deleted_at", None)
            normalized.pop("deleted_by", None)
            if normalized.get("status") == "DELETED":
                raise ValueError("Org units cannot be created as deleted.")
            await _ensure_org_unit_type_is_active(
                uow, normalized["company_id"], normalized["org_unit_type"]
            )
            repo = uow.get_repo(OrgUnitEntity, OrgUnit)
            return await repo.add(normalized)


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

    async def _execute(
        self,
        company_id: UUID | None = None,
        include_deleted: bool = False,
    ) -> list[OrgUnitEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(OrgUnitEntity, OrgUnit)
            criteria = [OrgUnit.company_id == company_id] if company_id is not None else []
            if not include_deleted:
                criteria.append(OrgUnit.deleted_at.is_(None))
            return await repo.find_all(
                *criteria,
                order_by=OrgUnit.org_unit_code,
                offset=0,
                limit=1000,
            )


class ListOrgUnitTypesUseCase(BaseUseCase[list[OrgUnitTypeEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID,
        include_inactive: bool = False,
        include_deleted: bool = False,
    ) -> list[OrgUnitTypeEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(OrgUnitTypeEntity, OrgUnitType)
            criteria = [OrgUnitType.company_id == company_id]
            if not include_inactive:
                criteria.append(OrgUnitType.is_active.is_(True))
            if not include_deleted:
                criteria.append(OrgUnitType.deleted_at.is_(None))
            return await repo.find_all(
                *criteria,
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
                if existing.deleted_at is not None:
                    raise ValueError("Deleted organization unit types cannot be edited.")
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


class DeleteOrgUnitTypeUseCase(BaseUseCase[OrgUnitTypeEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID,
        org_unit_type: str,
        actor_id: UUID,
    ) -> OrgUnitTypeEntity:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            type_model = (
                await uow.session.execute(
                    select(OrgUnitType)
                    .where(
                        OrgUnitType.company_id == company_id,
                        OrgUnitType.org_unit_type == org_unit_type,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if type_model is None:
                raise ValueError(f"Organization unit type '{org_unit_type}' not found.")
            if type_model.deleted_at is not None:
                raise ValueError("This organization unit type is already deleted.")

            now = datetime.now(timezone.utc)
            type_model.is_active = False
            type_model.is_default = False
            type_model.deleted_at = now
            type_model.deleted_by = actor_id
            await uow.session.flush()
            repo = uow.get_repo(OrgUnitTypeEntity, OrgUnitType)
            deleted = await repo.find_one(
                OrgUnitType.company_id == company_id,
                OrgUnitType.org_unit_type == org_unit_type,
            )
            if deleted is None:
                raise RuntimeError("Deleted organization unit type could not be reloaded.")
            return deleted


class UpdateOrgUnitUseCase(BaseUseCase[OrgUnitEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, org_unit_id: UUID, payload: dict[str, Any]) -> OrgUnitEntity:
        async with self.uow as uow:
            repo = uow.get_repo(OrgUnitEntity, OrgUnit)
            existing = await repo.find_one(OrgUnit.id == org_unit_id)
            if existing is None:
                raise ValueError("Org unit not found.")
            if existing.deleted_at is not None:
                raise ValueError("Deleted organization units cannot be edited.")

            normalized = _normalize_payload(payload)
            normalized.pop("deleted_at", None)
            normalized.pop("deleted_by", None)
            if normalized.get("status") == "DELETED":
                raise ValueError("Use the delete action to delete an organization unit.")
            entity_data = GenericMapper.to_entity(normalized, OrgUnitEntity)
            if entity_data is None:
                raise ValueError("Organization unit details are required.")
            await _ensure_org_unit_type_is_active(
                uow,
                entity_data.company_id,
                entity_data.org_unit_type,
                allow_inactive=(
                    entity_data.company_id == existing.company_id
                    and entity_data.org_unit_type == existing.org_unit_type
                ),
            )
            entity_data.id = org_unit_id
            changes = {
                key: value for key, value in entity_data.__dict__.items()
                if key not in (
                    "id", "created_at", "created_by", "row_version", "updated_at", "updated_by",
                    "deleted_at", "deleted_by",
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


async def _ensure_org_unit_type_is_active(
    uow: GenUnitOfWork,
    company_id: UUID,
    org_unit_type: str,
    *,
    allow_inactive: bool = False,
) -> None:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    result = await uow.session.execute(
        select(OrgUnitType.is_active, OrgUnitType.deleted_at).where(
            OrgUnitType.company_id == company_id,
            OrgUnitType.org_unit_type == org_unit_type,
        )
    )
    type_state = result.first()
    if type_state is None:
        raise ValueError(
            f"Organization unit type '{org_unit_type}' is not configured for this company."
        )
    if (not type_state.is_active or type_state.deleted_at is not None) and not allow_inactive:
        raise ValueError(
            f"Organization unit type '{org_unit_type}' is inactive or deleted and cannot be assigned."
        )


class DeleteOrgUnitUseCase(BaseUseCase[OrgUnitEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, org_unit_id: UUID, actor_id: UUID) -> OrgUnitEntity:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            org_unit = (
                await uow.session.execute(
                    select(OrgUnit).where(OrgUnit.id == org_unit_id).with_for_update()
                )
            ).scalar_one_or_none()
            if org_unit is None:
                raise ValueError("Org unit not found.")
            if org_unit.deleted_at is not None:
                raise ValueError("This organization unit is already deleted.")

            active_children = (
                await uow.session.execute(
                    select(OrgUnit.org_unit_code).where(
                        OrgUnit.parent_org_unit_id == org_unit_id,
                        OrgUnit.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            if active_children:
                raise ValueError(
                    "Delete or reassign the child organization units first: "
                    + ", ".join(sorted(active_children))
                    + "."
                )

            now = datetime.now(timezone.utc)
            org_unit.status = "DELETED"
            org_unit.is_active = False
            org_unit.deleted_at = now
            org_unit.deleted_by = actor_id
            org_unit.updated_at = now
            org_unit.updated_by = actor_id
            org_unit.row_version = (org_unit.row_version or 0) + 1
            await uow.session.flush()

            repo = uow.get_repo(OrgUnitEntity, OrgUnit)
            deleted = await repo.find_one(OrgUnit.id == org_unit_id)
            if deleted is None:
                raise RuntimeError("Deleted organization unit could not be reloaded.")
            return deleted
