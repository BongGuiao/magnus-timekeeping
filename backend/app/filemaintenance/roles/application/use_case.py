from datetime import date
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.auth.domain.entities.user import RoleEntity, UserRoleEntity
from app.auth.infrastructure.db_model import RoleModel
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.roles.application.payroll_access import (
    PayrollAccessViolationError,
    role_grants_restricted_payroll,
)
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel


class UserRoleReferenceError(ValueError):
    pass


class RoleConflictError(ValueError):
    pass


class UserRoleOverlapError(ValueError):
    pass


def _translate_role_integrity_error(error: IntegrityError) -> NoReturn:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint_name in {"roles_role_code_key", "uq_roles_role_code"}:
        raise RoleConflictError("A role with this code already exists.") from error
    raise error


class CreateRoleUseCase(BaseUseCase[RoleEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> RoleEntity:
        try:
            async with self.uow as uow:
                repo = uow.get_repo(RoleEntity, RoleModel)
                return await repo.add(payload)
        except IntegrityError as error:
            _translate_role_integrity_error(error)


class GetRoleUseCase(BaseUseCase[RoleEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, role_id: UUID) -> RoleEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(RoleEntity, RoleModel)
            return await repo.find_one(RoleModel.id == role_id)


class ListRolesUseCase(BaseUseCase[list[RoleEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        is_active: bool | None = None,
        role_code: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[RoleEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(RoleEntity, RoleModel)
            criteria = []
            if is_active is not None:
                criteria.append(RoleModel.is_active.is_(is_active))
            if role_code is not None:
                criteria.append(RoleModel.role_code == role_code.upper())
            return await repo.find_all(
                *criteria,
                order_by=RoleModel.role_name,
                offset=offset,
                limit=limit,
            )


class UpdateRoleUseCase(BaseUseCase[RoleEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        role_id: UUID,
        payload: dict[str, Any],
    ) -> RoleEntity | None:
        try:
            async with self.uow as uow:
                repo = uow.get_repo(RoleEntity, RoleModel)
                existing = await repo.find_one(RoleModel.id == role_id)
                if existing is None:
                    return None
                if existing.is_system_role and (
                    "role_code" in payload or "is_system_role" in payload
                ):
                    raise ValueError("System role codes and system status cannot be changed.")
                updated = RoleEntity(
                    **{
                        **existing.__dict__,
                        **payload,
                        "id": role_id,
                        "row_version": (existing.row_version or 0) + 1,
                    }
                )
                return await repo.update(updated)
        except IntegrityError as error:
            _translate_role_integrity_error(error)


class DeactivateRoleUseCase(BaseUseCase[RoleEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, role_id: UUID, actor_id: UUID) -> RoleEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(RoleEntity, RoleModel)
            existing = await repo.find_one(RoleModel.id == role_id)
            if existing is None:
                return None
            if existing.is_system_role:
                raise ValueError("System roles cannot be deactivated.")
            values = stamp_audit_fields({"is_active": False}, actor_id, creating=False)
            return await repo.update(
                RoleEntity(
                    **{
                        **existing.__dict__,
                        **values,
                        "row_version": (existing.row_version or 0) + 1,
                    }
                )
            )


def _translate_integrity_error(error: IntegrityError) -> NoReturn:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint_name in {
        "user_roles_user_id_fkey",
        "user_roles_role_id_fkey",
        "user_roles_company_id_fkey",
        "user_roles_org_unit_id_fkey",
        "user_roles_assigned_by_fkey",
    }:
        raise UserRoleReferenceError(
            "The user, role, company, org unit, or assigning user does not exist."
        ) from error
    if constraint_name == "ck_user_role_effective_dates":
        raise ValueError("effective_to must be on or after effective_from.") from error
    raise error


def _validate_effective_dates(effective_from: date, effective_to: date | None) -> None:
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("effective_to must be on or after effective_from.")


def _date_ranges_overlap(
    first_from: date,
    first_to: date | None,
    second_from: date,
    second_to: date | None,
) -> bool:
    return (
        (first_to is None or second_from <= first_to)
        and (second_to is None or first_from <= second_to)
    )


async def _ensure_no_overlapping_user_role(
    uow: GenUnitOfWork,
    *,
    user_id: UUID,
    role_id: UUID,
    company_id: UUID | None,
    org_unit_id: UUID | None,
    effective_from: date,
    effective_to: date | None,
    exclude_assignment_id: UUID | None = None,
) -> None:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")

    criteria = [
        UserRoleModel.user_id == user_id,
        UserRoleModel.role_id == role_id,
        (UserRoleModel.effective_to.is_(None))
        | (UserRoleModel.effective_to >= effective_from),
    ]
    if company_id is not None:
        criteria.append(
            or_(
                UserRoleModel.company_id.is_(None),
                UserRoleModel.company_id == company_id,
            )
        )
    if org_unit_id is not None:
        criteria.append(
            or_(
                UserRoleModel.org_unit_id.is_(None),
                UserRoleModel.org_unit_id == org_unit_id,
            )
        )
    if effective_to is not None:
        criteria.append(UserRoleModel.effective_from <= effective_to)
    if exclude_assignment_id is not None:
        criteria.append(UserRoleModel.id != exclude_assignment_id)
    overlapping_assignment_id = await uow.session.scalar(
        select(UserRoleModel.id).where(*criteria).limit(1)
    )
    if overlapping_assignment_id is not None:
        raise UserRoleOverlapError(
            "This employee already has an overlapping assignment for the selected role and scope."
        )


SELF_ASSIGN_PAYROLL_ROLE_MESSAGE = (
    "You cannot assign or extend a payroll-capable role for your own account. "
    "Payroll access is restricted to HR personnel."
)


async def _role_grants_restricted_payroll(uow: GenUnitOfWork, role_id: UUID) -> bool:
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    return await role_grants_restricted_payroll(uow.session, role_id)


def _only_narrows_effective_to(existing: UserRoleEntity, payload: dict[str, Any]) -> bool:
    """Ending one's own payroll role early is allowed; anything else is not."""
    for key, value in payload.items():
        if key != "effective_to" and getattr(existing, key, None) != value:
            return False
    if "effective_to" not in payload:
        return False
    new_effective_to = payload["effective_to"]
    if new_effective_to is None:
        return False
    return existing.effective_to is None or new_effective_to <= existing.effective_to


class CreateUserRoleUseCase(BaseUseCase[UserRoleEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> UserRoleEntity:
        _validate_effective_dates(payload["effective_from"], payload.get("effective_to"))
        try:
            async with self.uow as uow:
                if (
                    payload.get("assigned_by") is not None
                    and payload.get("user_id") == payload.get("assigned_by")
                    and await _role_grants_restricted_payroll(uow, payload["role_id"])
                ):
                    raise PayrollAccessViolationError(SELF_ASSIGN_PAYROLL_ROLE_MESSAGE)
                await _ensure_no_overlapping_user_role(
                    uow,
                    user_id=payload["user_id"],
                    role_id=payload["role_id"],
                    company_id=payload.get("company_id"),
                    org_unit_id=payload.get("org_unit_id"),
                    effective_from=payload["effective_from"],
                    effective_to=payload.get("effective_to"),
                )
                repo = uow.get_repo(UserRoleEntity, UserRoleModel)
                return await repo.add(payload)
        except IntegrityError as error:
            _translate_integrity_error(error)


class GetUserRoleUseCase(BaseUseCase[UserRoleEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, user_role_id: UUID) -> UserRoleEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(UserRoleEntity, UserRoleModel)
            return await repo.find_one(UserRoleModel.id == user_role_id)


class ListAvailableRolesUseCase(BaseUseCase[list[RoleEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self) -> list[RoleEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(RoleEntity, RoleModel)
            return await repo.find_all(
                RoleModel.is_active.is_(True),
                order_by=RoleModel.role_name,
                offset=0,
                limit=1000,
            )


class ListUserRolesUseCase(BaseUseCase[list[UserRoleEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        user_id: UUID | None = None,
        role_id: UUID | None = None,
        company_id: UUID | None = None,
        org_unit_id: UUID | None = None,
        effective_on: date | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[UserRoleEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(UserRoleEntity, UserRoleModel)
            criteria = []
            if user_id is not None:
                criteria.append(UserRoleModel.user_id == user_id)
            if role_id is not None:
                criteria.append(UserRoleModel.role_id == role_id)
            if company_id is not None:
                criteria.append(UserRoleModel.company_id == company_id)
            if org_unit_id is not None:
                criteria.append(UserRoleModel.org_unit_id == org_unit_id)
            if effective_on is not None:
                criteria.extend(
                    (
                        UserRoleModel.effective_from <= effective_on,
                        (UserRoleModel.effective_to.is_(None))
                        | (UserRoleModel.effective_to >= effective_on),
                    )
                )
            return await repo.find_all(
                *criteria,
                order_by=(UserRoleModel.effective_from.desc(), UserRoleModel.id),
                offset=offset,
                limit=limit,
            )


class UpdateUserRoleUseCase(BaseUseCase[UserRoleEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        user_role_id: UUID,
        payload: dict[str, Any],
        actor_id: UUID | None = None,
    ) -> UserRoleEntity | None:
        try:
            async with self.uow as uow:
                repo = uow.get_repo(UserRoleEntity, UserRoleModel)
                existing = await repo.find_one(UserRoleModel.id == user_role_id)
                if existing is None:
                    return None

                merged = {**existing.__dict__, **payload}
                _validate_effective_dates(
                    merged["effective_from"],
                    merged.get("effective_to"),
                )
                if (
                    actor_id is not None
                    and merged.get("user_id") == actor_id
                    and not _only_narrows_effective_to(existing, payload)
                    and await _role_grants_restricted_payroll(uow, merged["role_id"])
                ):
                    raise PayrollAccessViolationError(SELF_ASSIGN_PAYROLL_ROLE_MESSAGE)
                await _ensure_no_overlapping_user_role(
                    uow,
                    user_id=merged["user_id"],
                    role_id=merged["role_id"],
                    company_id=merged.get("company_id"),
                    org_unit_id=merged.get("org_unit_id"),
                    effective_from=merged["effective_from"],
                    effective_to=merged.get("effective_to"),
                    exclude_assignment_id=user_role_id,
                )
                entity = GenericMapper.to_entity(merged, UserRoleEntity)
                return await repo.update(entity)
        except IntegrityError as error:
            _translate_integrity_error(error)