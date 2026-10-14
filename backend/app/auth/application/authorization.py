from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, or_, select

from app.auth.domain.entities.user import AccountStatus
from app.auth.infrastructure.db_model import RoleModel
from app.auth.infrastructure.db_model import UserModel
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel
from app.filemaintenance.roles.infrastructure.permission_db_model import PermissionModel
from app.filemaintenance.roles.infrastructure.role_permission_db_model import RolePermissionModel

PH_TIMEZONE = ZoneInfo("Asia/Manila")


@dataclass(frozen=True)
class CurrentAuthorization:
    role_codes: list[str]
    permission_codes: list[str]


class GetCurrentAuthorizationUseCase(BaseUseCase[CurrentAuthorization]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, user_id: UUID) -> CurrentAuthorization:
        today = datetime.now(PH_TIMEZONE).date()
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            assignments = (
                select(UserRoleModel.role_id)
                .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
                .join(UserModel, UserModel.id == UserRoleModel.user_id)
                .where(
                    UserRoleModel.user_id == user_id,
                    UserRoleModel.effective_from <= today,
                    or_(UserRoleModel.effective_to.is_(None), UserRoleModel.effective_to >= today),
                    RoleModel.is_active.is_(True),
                    UserModel.is_active.is_(True),
                    UserModel.account_status == AccountStatus.ACTIVE.value,
                )
                .subquery()
            )
            role_codes = await uow.session.scalars(
                select(distinct(RoleModel.role_code))
                .join(assignments, assignments.c.role_id == RoleModel.id)
                .order_by(RoleModel.role_code)
            )
            permission_codes = await uow.session.scalars(
                select(distinct(PermissionModel.permission_code))
                .join(
                    RolePermissionModel,
                    RolePermissionModel.permission_id == PermissionModel.id,
                )
                .join(RoleModel, RoleModel.id == RolePermissionModel.role_id)
                .join(assignments, assignments.c.role_id == RoleModel.id)
                .where(
                    RolePermissionModel.allowed.is_(True),
                    PermissionModel.is_active.is_(True),
                )
                .order_by(PermissionModel.permission_code)
            )
            return CurrentAuthorization(
                role_codes=list(role_codes),
                permission_codes=list(permission_codes),
            )
