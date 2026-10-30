from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

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

    async def _execute(self, company_id: UUID, include_inactive: bool = False) -> list[OperationalGroupEntity]:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            criteria = [OperationalGroupModel.company_id == company_id]
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
            existing = await repo.find_one(
                OperationalGroupModel.company_id == company_id,
                OperationalGroupModel.operational_group == code,
            )
            if existing is None:
                raise OperationalGroupNotFoundError("Operational group not found.")
            updated = await repo.update(replace(existing, **payload))
            return existing, updated


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
    if not group.is_active and existing_assignment != (company_id, code):
        raise ValueError("Operational group is inactive and cannot be assigned.")
