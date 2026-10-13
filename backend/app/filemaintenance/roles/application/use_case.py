from datetime import date
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.auth.domain.entities.user import RoleEntity, UserRoleEntity
from app.auth.infrastructure.db_model import RoleModel
from app.core.audit_logging import stamp_audit_fields
from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel


class UserRoleReferenceError(ValueError):
    pass


class RoleConflictError(ValueError):
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


class CreateUserRoleUseCase(BaseUseCase[UserRoleEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> UserRoleEntity:
        _validate_effective_dates(payload["effective_from"], payload.get("effective_to"))
        try:
            async with self.uow as uow:
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
                entity = GenericMapper.to_entity(merged, UserRoleEntity)
                return await repo.update(entity)
        except IntegrityError as error:
            _translate_integrity_error(error)