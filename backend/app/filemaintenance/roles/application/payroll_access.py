"""Management directive: payroll is restricted to HR personnel.

System administrators (IT operations) manage roles and users but must never
obtain payroll rights, neither directly on their role nor by assigning a
payroll-capable role to themselves.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.infrastructure.db_model import RoleModel
from app.filemaintenance.roles.infrastructure.permission_db_model import PermissionModel
from app.filemaintenance.roles.infrastructure.role_permission_db_model import RolePermissionModel

SYSTEM_ADMIN_ROLE_CODES = frozenset({"SYSTEM_ADMIN", "SYSTEM_ADMINISTRATOR"})
PAYROLL_PERMISSION_PREFIX = "payroll."
SELF_SERVICE_PAYROLL_PERMISSION_CODES = frozenset({"payroll.read_own", "payroll.acknowledge_team"})


class PayrollAccessViolationError(ValueError):
    pass


def is_payroll_permission(permission_code: str) -> bool:
    return permission_code.startswith(PAYROLL_PERMISSION_PREFIX)


def is_restricted_payroll_permission(permission_code: str) -> bool:
    return (
        is_payroll_permission(permission_code)
        and permission_code not in SELF_SERVICE_PAYROLL_PERMISSION_CODES
    )


def is_system_admin_role(role_code: str | None) -> bool:
    return (role_code or "").upper() in SYSTEM_ADMIN_ROLE_CODES


def ensure_role_permission_change_allowed(
    role_code: str | None,
    existing_codes: set[str],
    requested_codes: set[str],
) -> None:
    if is_system_admin_role(role_code):
        payroll_codes = sorted(code for code in requested_codes if is_payroll_permission(code))
        if payroll_codes:
            raise PayrollAccessViolationError(
                "Payroll permissions cannot be granted to system administrator roles: "
                + ", ".join(payroll_codes)
            )
    existing_restricted = {code for code in existing_codes if is_restricted_payroll_permission(code)}
    requested_restricted = {code for code in requested_codes if is_restricted_payroll_permission(code)}
    if existing_restricted != requested_restricted:
        changed = sorted(existing_restricted ^ requested_restricted)
        raise PayrollAccessViolationError(
            "Payroll permissions are managed by HR and cannot be changed here: "
            + ", ".join(changed)
        )


async def role_grants_restricted_payroll(session: AsyncSession, role_id: UUID) -> bool:
    granted = await session.scalar(
        select(PermissionModel.permission_code)
        .join(RolePermissionModel, RolePermissionModel.permission_id == PermissionModel.id)
        .where(
            RolePermissionModel.role_id == role_id,
            RolePermissionModel.allowed.is_(True),
            PermissionModel.is_active.is_(True),
            PermissionModel.permission_code.like(f"{PAYROLL_PERMISSION_PREFIX}%"),
            PermissionModel.permission_code.not_in(SELF_SERVICE_PAYROLL_PERMISSION_CODES),
        )
        .limit(1)
    )
    return granted is not None


async def get_role_code(session: AsyncSession, role_id: UUID) -> str | None:
    return await session.scalar(select(RoleModel.role_code).where(RoleModel.id == role_id))
