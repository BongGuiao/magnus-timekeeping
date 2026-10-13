from dataclasses import replace
from typing import Any, Dict
from uuid import UUID

from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.core.generics.mapper import GenericMapper
from app.filemaintenance.companies.domain.entities.company import CompanyEntity
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel


class CreateCompanyUseCase(BaseUseCase[CompanyEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: Dict[str, Any]) -> CompanyEntity:
        async with self.uow as uow:
            repo = uow.get_repo(CompanyEntity, CompanyModel)
            created = await repo.add(payload)
            return created


class GetCompanyUseCase(BaseUseCase[CompanyEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, company_id: UUID) -> CompanyEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(CompanyEntity, CompanyModel)
            return await repo.find_one(CompanyModel.id == company_id)


class ListCompaniesUseCase(BaseUseCase[list[CompanyEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self) -> list[CompanyEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(CompanyEntity, CompanyModel)
            return await repo.find_all(
                order_by=CompanyModel.company_code,
                offset=0,
                limit=1000,
            )


class UpdateCompanyUseCase(BaseUseCase[CompanyEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, id: UUID, payload: Dict[str, Any]) -> CompanyEntity:
        async with self.uow as uow:
            repo = uow.get_repo(CompanyEntity, CompanyModel)
            existing = await repo.find_one(CompanyModel.id == id)
            if existing is None:
                raise ValueError("Company not found.")
            entity_data = GenericMapper.to_entity(payload, CompanyEntity)
            entity_data.id = id
            entity_data.row_version = (existing.row_version or 0) + 1
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