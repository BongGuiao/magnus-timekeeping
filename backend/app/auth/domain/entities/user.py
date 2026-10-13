from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID


class Role(str, Enum):
    """Application access level carried in the JWT `role` claim."""

    ADMIN = "admin"
    USER = "user"


class AccountStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    DISABLED = "DISABLED"


DEFAULT_SIGNUP_ROLE_CODE = "SYSTEM_ADMIN"
DEFAULT_EMPLOYEE_ROLE_CODE = "EMPLOYEE"
# identity.roles codes that grant the application-level ADMIN access.
ADMIN_ROLE_CODES = frozenset({"SYSTEM_ADMIN", "SYSTEM_ADMINISTRATOR", "HR_ADMIN"})


def resolve_app_role(role_codes: list[str] | set[str] | tuple[str, ...]) -> Role:
    return Role.ADMIN if ADMIN_ROLE_CODES.intersection(role_codes) else Role.USER


@dataclass
class UserEntity:
    """Maps identity.users."""

    username: str
    password_hash: str
    email: Optional[str] = None
    employee_id: Optional[UUID] = None
    account_status: str = AccountStatus.PENDING.value
    failed_login_count: int = 0
    locked_until: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    mfa_enabled: bool = False
    password_changed_at: Optional[datetime] = None
    is_active: bool = True
    id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[UUID] = None
    row_version: Optional[int] = None


@dataclass
class RoleEntity:
    """Maps identity.roles."""

    role_code: str
    role_name: str
    scope_type: str
    description: Optional[str] = None
    is_system_role: bool = False
    is_active: bool = True
    id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[UUID] = None
    row_version: Optional[int] = None


@dataclass
class UserRoleEntity:
    """Maps identity.user_roles."""

    user_id: UUID
    role_id: UUID
    effective_from: date
    company_id: Optional[UUID] = None
    org_unit_id: Optional[UUID] = None
    effective_to: Optional[date] = None
    assigned_by: Optional[UUID] = None
    id: Optional[UUID] = None
