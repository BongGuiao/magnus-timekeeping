from fastapi import Depends

from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.roles.application.permission_use_cases import (
    GetRolePermissionsUseCase,
    ListPermissionsUseCase,
    SetRolePermissionsUseCase,
)
from app.filemaintenance.roles.application.use_case import (
    CreateRoleUseCase,
    CreateUserRoleUseCase,
    DeactivateRoleUseCase,
    GetRoleUseCase,
    GetUserRoleUseCase,
    ListAvailableRolesUseCase,
    ListRolesUseCase,
    ListUserRolesUseCase,
    UpdateRoleUseCase,
    UpdateUserRoleUseCase,
)


def get_list_permissions_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListPermissionsUseCase:
    return ListPermissionsUseCase(uow)


def get_get_role_permissions_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetRolePermissionsUseCase:
    return GetRolePermissionsUseCase(uow)


def get_set_role_permissions_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> SetRolePermissionsUseCase:
    return SetRolePermissionsUseCase(uow)


def get_create_role_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateRoleUseCase:
    return CreateRoleUseCase(uow)


def get_get_role_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetRoleUseCase:
    return GetRoleUseCase(uow)


def get_list_roles_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListRolesUseCase:
    return ListRolesUseCase(uow)


def get_update_role_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateRoleUseCase:
    return UpdateRoleUseCase(uow)


def get_deactivate_role_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> DeactivateRoleUseCase:
    return DeactivateRoleUseCase(uow)


def get_create_user_role_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> CreateUserRoleUseCase:
    return CreateUserRoleUseCase(uow)


def get_get_user_role_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> GetUserRoleUseCase:
    return GetUserRoleUseCase(uow)


def get_list_available_roles_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListAvailableRolesUseCase:
    return ListAvailableRolesUseCase(uow)


def get_list_user_roles_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> ListUserRolesUseCase:
    return ListUserRolesUseCase(uow)


def get_update_user_role_use_case(
    uow: GenUnitOfWork = Depends(get_unit_of_work),
) -> UpdateUserRoleUseCase:
    return UpdateUserRoleUseCase(uow)