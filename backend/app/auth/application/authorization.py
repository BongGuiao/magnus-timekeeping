from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, or_, select

from app.auth.domain.entities.user import AccountStatus
from app.auth.infrastructure.approval_routing import (
    ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS,
    active_org_unit_manager_condition,
)
from app.auth.infrastructure.db_model import RoleModel
from app.auth.infrastructure.db_model import UserModel
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel
from app.filemaintenance.roles.infrastructure.permission_db_model import PermissionModel
from app.filemaintenance.roles.infrastructure.role_permission_db_model import RolePermissionModel

PH_TIMEZONE = ZoneInfo("Asia/Manila")


@dataclass(frozen=True)
class CurrentAuthorization:
    role_codes: list[str]
    permission_codes: list[str]
    employee_code: str | None
    employee_id: UUID | None = None


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
            employee = (await uow.session.execute(
                select(
                    EmployeeModel.id, EmployeeModel.employee_no,
                    EmployeeModel.is_active, EmployeeModel.record_status,
                )
                .join(UserModel, UserModel.employee_id == EmployeeModel.id)
                .where(
                    UserModel.id == user_id,
                    UserModel.is_active.is_(True),
                    UserModel.account_status == AccountStatus.ACTIVE.value,
                )
            )).first()
            effective_permission_codes = set(permission_codes)
            is_active_employee = bool(employee and employee.is_active and employee.record_status == "ACTIVE")
            if is_active_employee and await uow.session.scalar(
                select(active_org_unit_manager_condition(employee.id, today))
            ):
                effective_permission_codes |= ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS
            return CurrentAuthorization(
                role_codes=list(role_codes),
                permission_codes=sorted(effective_permission_codes),
                employee_code=employee.employee_no if employee else None,
                employee_id=employee.id if is_active_employee else None,
            )
