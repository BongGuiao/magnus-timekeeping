from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import func

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.leaves.domain.entities.leave_type import LeaveTypeEntity
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = payload.copy()
    for field in ("company_id", "created_by", "updated_by", "id"):
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = UUID(value)
    return normalized


class CreateLeaveTypeUseCase(BaseUseCase[LeaveTypeEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> LeaveTypeEntity:
        async with self.uow as uow:
            repo = uow.get_repo(LeaveTypeEntity, LeaveTypeModel)
            return await repo.add(_normalize_payload(payload))


class GetLeaveTypeUseCase(BaseUseCase[LeaveTypeEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, leave_type_id: UUID) -> LeaveTypeEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(LeaveTypeEntity, LeaveTypeModel)
            return await repo.find_one(LeaveTypeModel.id == leave_type_id)


class ListLeaveTypesUseCase(BaseUseCase[list[LeaveTypeEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID | None = None,
        leave_status: str | None = None,
        is_active: bool | None = None,
        leave_code: str | None = None,
    ) -> list[LeaveTypeEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(LeaveTypeEntity, LeaveTypeModel)
            criteria = []
            if company_id is not None:
                criteria.append(LeaveTypeModel.company_id == company_id)
            if leave_code is not None:
                criteria.append(func.upper(LeaveTypeModel.leave_code) == leave_code.strip().upper())
            if leave_status is not None:
                criteria.append(LeaveTypeModel.status == leave_status)
            if is_active is not None:
                criteria.append(LeaveTypeModel.is_active == is_active)
            return await repo.find_all(
                *criteria,
                order_by=(LeaveTypeModel.company_id, LeaveTypeModel.leave_code, LeaveTypeModel.effective_from.desc()),
                limit=1000,
            )


class UpdateLeaveTypeUseCase(BaseUseCase[LeaveTypeEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, leave_type_id: UUID, payload: dict[str, Any]) -> LeaveTypeEntity:
        async with self.uow as uow:
            repo = uow.get_repo(LeaveTypeEntity, LeaveTypeModel)
            existing = await repo.find_one(LeaveTypeModel.id == leave_type_id)
            if existing is None:
                raise ValueError("Leave type not found.")

            merged_payload = {**existing.__dict__, **_normalize_payload(payload)}
            effective_from = merged_payload.get("effective_from")
            effective_to = merged_payload.get("effective_to")
            if effective_to is not None and effective_to < effective_from:
                raise ValueError("effective_to must be on or after effective_from.")

            entity_data = GenericMapper.to_entity(merged_payload, LeaveTypeEntity)
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
