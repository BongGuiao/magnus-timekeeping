from dataclasses import replace
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.payroll_groups.domain.entities.payroll_group import PayrollGroupEntity
from app.filemaintenance.payroll_groups.infrastructure.db_model import PayrollGroupModel


class PayrollGroupConflictError(ValueError):
    pass


class PayrollGroupReferenceError(ValueError):
    pass


def _translate_integrity_error(error: IntegrityError) -> NoReturn:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint_name == "uq_payroll_groups_company_code":
        raise PayrollGroupConflictError(
            "A payroll group with this code already exists for the company."
        ) from error
    if constraint_name in (
        "payroll_groups_company_id_fkey",
        "payroll_groups_holiday_calendar_id_fkey",
    ):
        raise PayrollGroupReferenceError(
            "The company or holiday calendar does not exist."
        ) from error
    raise error


class CreatePayrollGroupUseCase(BaseUseCase[PayrollGroupEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> PayrollGroupEntity:
        try:
            async with self.uow as uow:
                repo = uow.get_repo(PayrollGroupEntity, PayrollGroupModel)
                return await repo.add(payload)
        except IntegrityError as error:
            _translate_integrity_error(error)


class GetPayrollGroupUseCase(BaseUseCase[PayrollGroupEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payroll_group_id: UUID) -> PayrollGroupEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(PayrollGroupEntity, PayrollGroupModel)
            return await repo.find_one(PayrollGroupModel.id == payroll_group_id)


class ListPayrollGroupsUseCase(BaseUseCase[list[PayrollGroupEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        company_id: UUID | None = None,
        group_status: str | None = None,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PayrollGroupEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(PayrollGroupEntity, PayrollGroupModel)
            criteria = []
            if company_id is not None:
                criteria.append(PayrollGroupModel.company_id == company_id)
            if group_status is not None:
                criteria.append(PayrollGroupModel.status == group_status)
            if is_active is not None:
                criteria.append(PayrollGroupModel.is_active.is_(is_active))
            return await repo.find_all(
                *criteria,
                order_by=(PayrollGroupModel.company_id, PayrollGroupModel.payroll_group_code),
                offset=offset,
                limit=limit,
            )


class UpdatePayrollGroupUseCase(BaseUseCase[PayrollGroupEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        payroll_group_id: UUID,
        payload: dict[str, Any],
    ) -> PayrollGroupEntity | None:
        try:
            async with self.uow as uow:
                repo = uow.get_repo(PayrollGroupEntity, PayrollGroupModel)
                existing = await repo.find_one(PayrollGroupModel.id == payroll_group_id)
                if existing is None:
                    return None

                merged = {**existing.__dict__, **payload}
                entity = GenericMapper.to_entity(merged, PayrollGroupEntity)
                changes = {
                    key: value
                    for key, value in entity.__dict__.items()
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
                    updated_at=entity.updated_at or existing.updated_at,
                    updated_by=entity.updated_by or existing.updated_by,
                    row_version=(existing.row_version or 0) + 1,
                )
                return await repo.update(updated)
        except IntegrityError as error:
            _translate_integrity_error(error)
