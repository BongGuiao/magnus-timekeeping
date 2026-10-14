from uuid import UUID

from sqlalchemy import delete, select

from app.auth.infrastructure.db_model import RoleModel
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.roles.infrastructure.permission_db_model import PermissionModel
from app.filemaintenance.roles.infrastructure.role_permission_db_model import RolePermissionModel


class UnknownPermissionCodesError(ValueError):
    def __init__(self, permission_codes: list[str]):
        self.permission_codes = permission_codes
        super().__init__(f"Unknown or inactive permission codes: {', '.join(permission_codes)}")


class ListPermissionsUseCase(BaseUseCase[list[PermissionModel]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self) -> list[PermissionModel]:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            permissions = await uow.session.scalars(
                select(PermissionModel)
                .where(PermissionModel.is_active.is_(True))
                .order_by(PermissionModel.permission_code)
            )
            return list(permissions)


class GetRolePermissionsUseCase(BaseUseCase[list[str] | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, role_id: UUID) -> list[str] | None:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            role = await uow.session.scalar(
                select(RoleModel.id).where(RoleModel.id == role_id)
            )
            if role is None:
                return None
            codes = await uow.session.scalars(
                select(PermissionModel.permission_code)
                .join(
                    RolePermissionModel,
                    RolePermissionModel.permission_id == PermissionModel.id,
                )
                .where(
                    RolePermissionModel.role_id == role_id,
                    RolePermissionModel.allowed.is_(True),
                    PermissionModel.is_active.is_(True),
                )
                .order_by(PermissionModel.permission_code)
            )
            return list(codes)


class SetRolePermissionsUseCase(BaseUseCase[list[str] | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, role_id: UUID, permission_codes: list[str]) -> list[str] | None:
        requested_codes = sorted(set(permission_codes))
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            role = await uow.session.scalar(
                select(RoleModel.id).where(RoleModel.id == role_id)
            )
            if role is None:
                return None

            permissions = await uow.session.scalars(
                select(PermissionModel).where(
                    PermissionModel.permission_code.in_(requested_codes),
                    PermissionModel.is_active.is_(True),
                )
            )
            permissions_by_code = {permission.permission_code: permission for permission in permissions}
            unknown_codes = sorted(set(requested_codes) - permissions_by_code.keys())
            if unknown_codes:
                raise UnknownPermissionCodesError(unknown_codes)

            await uow.session.execute(
                delete(RolePermissionModel).where(RolePermissionModel.role_id == role_id)
            )
            uow.session.add_all(
                [
                    RolePermissionModel(
                        role_id=role_id,
                        permission_id=permissions_by_code[code].id,
                        allowed=True,
                    )
                    for code in requested_codes
                ]
            )
            await uow.session.flush()
            return requested_codes
