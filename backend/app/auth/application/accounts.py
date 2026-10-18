"""Shared identity.users helpers used by auth, employee and attendance use cases."""

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select

from app.auth.domain.entities.user import (
    AccountStatus,
    Role,
    RoleEntity,
    UserEntity,
    UserRoleEntity,
    resolve_app_role,
)
from app.auth.infrastructure.db_model import RoleModel, UserModel, UserRoleModel
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.employees.domain.entities.employee import EmployeeEntity

PH_TIMEZONE = ZoneInfo("Asia/Manila")
DEFAULT_EMPLOYEE_PASSWORD = "Default123!"


def employee_display_name(employee: EmployeeEntity | None) -> str:
    if employee is None:
        return ""
    return employee.preferred_name or " ".join(
        part
        for part in (employee.first_name, employee.middle_name, employee.last_name, employee.suffix)
        if part
    )


def _session(uow: GenUnitOfWork):
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    return uow.session


async def get_active_role_codes(uow: GenUnitOfWork, user_id: UUID) -> list[str]:
    today = datetime.now(PH_TIMEZONE).date()
    rows = await _session(uow).scalars(
        select(RoleModel.role_code)
        .join(UserRoleModel, UserRoleModel.role_id == RoleModel.id)
        .where(
            UserRoleModel.user_id == user_id,
            UserRoleModel.effective_from <= today,
            or_(UserRoleModel.effective_to.is_(None), UserRoleModel.effective_to >= today),
            RoleModel.is_active.is_(True),
        )
        .order_by(RoleModel.role_code)
    )
    return list(dict.fromkeys(rows))


async def get_app_role(uow: GenUnitOfWork, user_id: UUID) -> tuple[Role, list[str]]:
    role_codes = await get_active_role_codes(uow, user_id)
    return resolve_app_role(role_codes), role_codes


async def find_user_conflict(
    uow: GenUnitOfWork,
    *,
    username: str,
    email: str | None,
    employee_id: UUID | None,
) -> UserEntity | None:
    conditions = [func.lower(UserModel.username) == username.lower()]
    if email:
        conditions.append(func.lower(UserModel.email) == email.lower())
    if employee_id is not None:
        conditions.append(UserModel.employee_id == employee_id)
        conditions.append(UserModel.id == employee_id)
    repo = uow.get_repo(UserEntity, UserModel)
    matches = await repo.find_all(or_(*conditions), limit=1)
    return matches[0] if matches else None


async def create_user_account(
    uow: GenUnitOfWork,
    *,
    employee: EmployeeEntity,
    email: str,
    password_hash: str,
    role_code: str,
    account_status: AccountStatus,
    actor_id: UUID | None,
    password_set_by_user: bool,
) -> tuple[UserEntity, RoleEntity]:
    """Creates identity.users + identity.user_roles for an employee.

    The user id intentionally equals hr.employees.id so existing face enrollment and
    attendance flows that pass the user id as the employee id keep working.
    """
    if employee.id is None:
        raise RuntimeError("Employee profile has no ID.")

    role_repo = uow.get_repo(RoleEntity, RoleModel)
    role = await role_repo.find_one(
        RoleModel.role_code == role_code.strip().upper(),
        RoleModel.is_active.is_(True),
    )
    if role is None or role.id is None:
        raise ValueError(f"Role '{role_code}' does not exist or is inactive.")

    username = employee.employee_no.strip()
    if await find_user_conflict(uow, username=username, email=email, employee_id=employee.id):
        raise ValueError("An account already exists for this employee number, employee or email.")

    now_utc = datetime.now(timezone.utc)
    user_repo = uow.get_repo(UserEntity, UserModel)
    user = await user_repo.add(
        UserEntity(
            id=employee.id,
            employee_id=employee.id,
            username=username,
            email=email,
            password_hash=password_hash,
            account_status=account_status.value,
            password_changed_at=now_utc if password_set_by_user else None,
            is_active=account_status == AccountStatus.ACTIVE,
            created_by=actor_id,
            updated_by=actor_id,
        )
    )
    if user.id is None:
        raise RuntimeError("Created user account has no ID.")

    await uow.get_repo(UserRoleEntity, UserRoleModel).add(
        UserRoleEntity(
            user_id=user.id,
            role_id=role.id,
            effective_from=datetime.now(PH_TIMEZONE).date(),
            assigned_by=actor_id,
        )
    )
    return user, role


async def sync_user_account_with_employee(
    uow: GenUnitOfWork,
    *,
    employee: EmployeeEntity,
    email: str,
    actor_id: UUID | None,
    default_password_hash: str,
    default_role_code: str,
) -> UserEntity:
    """Keeps identity.users aligned with the employee profile after an update.

    - username follows employee_no, email follows personal_email
    - an archived/inactive employee disables the account; reactivating re-enables only DISABLED
      accounts (LOCKED/PENDING are administrative states and are left alone)
    - employees without an account get one, same as on creation
    """
    if employee.id is None:
        raise RuntimeError("Employee profile has no ID.")

    employee_active = employee.is_active and employee.record_status == "ACTIVE"
    user_repo = uow.get_repo(UserEntity, UserModel)
    user = await user_repo.find_one(UserModel.employee_id == employee.id)

    if user is None:
        created, _ = await create_user_account(
            uow,
            employee=employee,
            email=email,
            password_hash=default_password_hash,
            role_code=default_role_code,
            account_status=AccountStatus.ACTIVE if employee_active else AccountStatus.DISABLED,
            actor_id=actor_id,
            password_set_by_user=False,
        )
        return created

    username = employee.employee_no.strip()
    conflict_conditions = [func.lower(UserModel.username) == username.lower()]
    if email:
        conflict_conditions.append(func.lower(UserModel.email) == email.lower())
    conflicts = await user_repo.find_all(or_(*conflict_conditions), UserModel.id != user.id, limit=1)
    if conflicts:
        raise ValueError("Another account already uses this employee number or personal email.")

    if not employee_active:
        account_status = AccountStatus.DISABLED.value
    elif user.account_status == AccountStatus.DISABLED.value:
        account_status = AccountStatus.ACTIVE.value
    else:
        account_status = user.account_status

    changes = {
        "username": username,
        "email": email,
        "account_status": account_status,
        "is_active": employee_active,
    }
    if all(getattr(user, key) == value for key, value in changes.items()):
        return user
    return await user_repo.update(replace(user, **changes, updated_by=actor_id or user.updated_by))


def is_login_allowed(user: UserEntity, now_utc: datetime) -> str | None:
    """Returns a rejection message, or None when the account may sign in."""
    if not user.is_active or user.account_status == AccountStatus.DISABLED.value:
        return "User account is inactive."
    if user.account_status == AccountStatus.PENDING.value:
        return "User account is pending activation."
    if user.account_status == AccountStatus.LOCKED.value:
        return "User account is locked. Please contact your administrator."
    if user.locked_until is not None and _as_utc(user.locked_until) > now_utc:
        return "Too many failed login attempts. Please try again later."
    return None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
