from dataclasses import replace
from datetime import date, datetime
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.payroll_cutoffs.domain.entities.payroll_cutoff import PayrollCutoffEntity
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel


class PayrollCutoffConflictError(ValueError):
    pass


class PayrollCutoffReferenceError(ValueError):
    pass


def _translate_integrity_error(error: IntegrityError) -> NoReturn:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint_name in (
        "uq_cutoffs_payroll_group_code",
        "cutoffs_payroll_group_id_cutoff_code_key",
    ):
        raise PayrollCutoffConflictError(
            "A cutoff with this code already exists for the payroll group."
        ) from error
    if constraint_name in (
        "cutoffs_payroll_group_id_fkey",
        "cutoffs_locked_by_fkey",
    ):
        raise PayrollCutoffReferenceError(
            "The payroll group or locking user does not exist."
        ) from error
    if constraint_name == "fk_cutoff_export":
        raise PayrollCutoffReferenceError(
            "The export batch does not exist."
        ) from error
    raise error


def _validate_period(start: date, end: date) -> None:
    if end < start:
        raise ValueError("period_end must be on or after period_start.")


class CreatePayrollCutoffUseCase(BaseUseCase[PayrollCutoffEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> PayrollCutoffEntity:
        _validate_period(payload["period_start"], payload["period_end"])
        try:
            async with self.uow as uow:
                repo = uow.get_repo(PayrollCutoffEntity, PayrollCutoffModel)
                return await repo.add(payload)
        except IntegrityError as error:
            _translate_integrity_error(error)


class GetPayrollCutoffUseCase(BaseUseCase[PayrollCutoffEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, cutoff_id: UUID) -> PayrollCutoffEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(PayrollCutoffEntity, PayrollCutoffModel)
            return await repo.find_one(PayrollCutoffModel.id == cutoff_id)


class ListPayrollCutoffsUseCase(BaseUseCase[list[PayrollCutoffEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        payroll_group_id: UUID | None = None,
        cutoff_status: str | None = None,
        is_active: bool | None = None,
        period_start_from: date | None = None,
        period_start_to: date | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PayrollCutoffEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(PayrollCutoffEntity, PayrollCutoffModel)
            criteria = []
            if payroll_group_id is not None:
                criteria.append(PayrollCutoffModel.payroll_group_id == payroll_group_id)
            if cutoff_status is not None:
                criteria.append(PayrollCutoffModel.status == cutoff_status)
            if is_active is not None:
                criteria.append(PayrollCutoffModel.is_active.is_(is_active))
            if period_start_from is not None:
                criteria.append(PayrollCutoffModel.period_start >= period_start_from)
            if period_start_to is not None:
                criteria.append(PayrollCutoffModel.period_start <= period_start_to)
            return await repo.find_all(
                *criteria,
                order_by=(PayrollCutoffModel.period_start.desc(), PayrollCutoffModel.cutoff_code),
                offset=offset,
                limit=limit,
            )


class UpdatePayrollCutoffUseCase(BaseUseCase[PayrollCutoffEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        cutoff_id: UUID,
        payload: dict[str, Any],
    ) -> PayrollCutoffEntity | None:
        try:
            async with self.uow as uow:
                repo = uow.get_repo(PayrollCutoffEntity, PayrollCutoffModel)
                existing = await repo.find_one(PayrollCutoffModel.id == cutoff_id)
                if existing is None:
                    return None

                merged = {**existing.__dict__, **payload}
                _validate_period(merged["period_start"], merged["period_end"])
                entity = GenericMapper.to_entity(merged, PayrollCutoffEntity)
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
