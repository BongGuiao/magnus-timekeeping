from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.attendance.application.clock import utc_now
from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel
from app.filemaintenance.operational_groups.domain.entities.operational_group import OperationalGroupEntity
from app.filemaintenance.operational_groups.infrastructure.db_model import OperationalGroupModel


class OperationalGroupConflictError(ValueError):
    pass


class OperationalGroupNotFoundError(ValueError):
    pass


class ListOperationalGroupsUseCase(BaseUseCase[list[OperationalGroupEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self, company_id: UUID, include_inactive: bool = False, include_deleted: bool = False,
    ) -> list[OperationalGroupEntity]:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            criteria = [OperationalGroupModel.company_id == company_id]
            if not include_deleted:
                criteria.append(OperationalGroupModel.deleted_at.is_(None))
            if not include_inactive:
                criteria.append(OperationalGroupModel.is_active.is_(True))
            groups = (await uow.session.scalars(
                select(OperationalGroupModel).where(*criteria).order_by(
                    OperationalGroupModel.sort_order, OperationalGroupModel.operational_group
                )
            )).all()
            return [
                OperationalGroupEntity(
                    company_id=group.company_id,
                    operational_group=group.operational_group,
                    display_name=group.display_name,
                    sort_order=group.sort_order,
                    is_active=group.is_active,
                    deleted_at=group.deleted_at,
                    deleted_by=group.deleted_by,
                )
                for group in groups
            ]


class CreateOperationalGroupUseCase(BaseUseCase[OperationalGroupEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> OperationalGroupEntity:
        try:
            async with self.uow as uow:
                if uow.session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                company_id = await uow.session.scalar(
                    select(CompanyModel.id).where(CompanyModel.id == payload["company_id"])
                )
                if company_id is None:
                    raise ValueError("Company not found.")
                repo = uow.get_repo(OperationalGroupEntity, OperationalGroupModel)
                existing = await repo.find_one(
                    OperationalGroupModel.company_id == company_id,
                    OperationalGroupModel.operational_group == payload["operational_group"],
                )
                if existing is not None:
                    raise OperationalGroupConflictError("Operational group code already exists for this company.")
                return await repo.add(OperationalGroupEntity(**payload))
        except IntegrityError as error:
            raise OperationalGroupConflictError(
                "The operational group conflicts with an existing group or company."
            ) from error


class UpdateOperationalGroupUseCase(BaseUseCase[tuple[OperationalGroupEntity, OperationalGroupEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self, company_id: UUID, code: str, payload: dict[str, Any]
    ) -> tuple[OperationalGroupEntity, OperationalGroupEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(OperationalGroupEntity, OperationalGroupModel)
            existing = await _lock_group(uow, company_id, code)
            if existing.deleted_at is not None:
                raise OperationalGroupConflictError("Restore the deleted operational group before editing it.")
            updated = await repo.update(replace(existing, **payload))
            return existing, updated


async def _lock_group(uow: GenUnitOfWork, company_id: UUID, code: str) -> OperationalGroupEntity:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    group = await uow.session.scalar(
        select(OperationalGroupModel).where(
            OperationalGroupModel.company_id == company_id,
            OperationalGroupModel.operational_group == code,
        ).with_for_update()
    )
    if group is None:
        raise OperationalGroupNotFoundError("Operational group not found.")
    entity = GenericMapper.to_entity(group, OperationalGroupEntity)
    if entity is None:
        raise RuntimeError("The operational group could not be mapped.")
    return entity


class DeleteOperationalGroupUseCase(BaseUseCase[tuple[OperationalGroupEntity, OperationalGroupEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self, company_id: UUID, code: str, user_id: UUID,
    ) -> tuple[OperationalGroupEntity, OperationalGroupEntity]:
        async with self.uow as uow:
            existing = await _lock_group(uow, company_id, code)
            if existing.deleted_at is not None:
                raise OperationalGroupConflictError("Operational group is already deleted.")
            deleted = replace(existing, is_active=False, deleted_at=utc_now(), deleted_by=user_id)
            saved = await uow.get_repo(OperationalGroupEntity, OperationalGroupModel).update(deleted)
            return existing, saved


class RestoreOperationalGroupUseCase(BaseUseCase[tuple[OperationalGroupEntity, OperationalGroupEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, company_id: UUID, code: str) -> tuple[OperationalGroupEntity, OperationalGroupEntity]:
        async with self.uow as uow:
            existing = await _lock_group(uow, company_id, code)
            if existing.deleted_at is None:
                raise OperationalGroupConflictError("Operational group is not deleted.")
            restored = replace(existing, is_active=False, deleted_at=None, deleted_by=None)
            saved = await uow.get_repo(OperationalGroupEntity, OperationalGroupModel).update(restored)
            return existing, saved


async def ensure_operational_group_allowed(
    uow: GenUnitOfWork,
    company_id: UUID,
    code: str | None,
    existing_assignment: tuple[UUID, str | None] | None = None,
) -> None:
    if code is None:
        return
    if not isinstance(code, str) or not code or len(code) > 30:
        raise ValueError("Operational group must be a code of 1 to 30 characters.")
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    group = await uow.session.scalar(
        select(OperationalGroupModel)
        .where(
            OperationalGroupModel.company_id == company_id,
            OperationalGroupModel.operational_group == code,
        )
        .with_for_update(read=True)
    )
    if group is None:
        raise ValueError("Operational group does not exist for the selected company.")
    if group.deleted_at is not None and existing_assignment != (company_id, code):
        raise ValueError("Operational group is deleted and cannot be assigned.")
    if not group.is_active and existing_assignment != (company_id, code):
        raise ValueError("Operational group is inactive and cannot be assigned.")
