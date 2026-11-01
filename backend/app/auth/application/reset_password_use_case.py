from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from app.auth.application.accounts import DEFAULT_EMPLOYEE_PASSWORD as DEFAULT_PASSWORD
from app.auth.application.password_ports import AuditTrail, PasswordHasher, UserAccountUnitOfWork
from app.auth.domain import password_rules as rules
from app.auth.domain.exceptions import AccountNotFoundError
from app.core.generics.uc_base import BaseUseCase


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ResetPasswordInput:
    actor_id: UUID
    employee_code: str


@dataclass(frozen=True)
class ResetPasswordOutput:
    employee_code: str
    password_reset_at: datetime


class ResetPasswordToDefaultUseCase(BaseUseCase[ResetPasswordOutput]):
    """Lets a system administrator restore an employee's password to the default.

    The caller's system-administrator role is enforced at the transport layer.
    """

    def __init__(
        self,
        uow: UserAccountUnitOfWork,
        hasher: PasswordHasher,
        audit: AuditTrail,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self._uow = uow
        self._hasher = hasher
        self._audit = audit
        self._clock = clock

    async def _execute(self, data: ResetPasswordInput) -> ResetPasswordOutput:
        employee_code = data.employee_code.strip()
        if not employee_code:
            raise AccountNotFoundError("Enter an employee code.")

        now = self._clock()
        async with self._uow as uow:
            user = await uow.users.get_by_username_for_update(employee_code)
            if user is None or user.id is None:
                raise AccountNotFoundError("No user account was found for this employee code.")
            user = rules.after_password_reset(user, self._hasher.hash(DEFAULT_PASSWORD), data.actor_id)
            await uow.users.save(user)

        await self._audit.record(
            user_id=data.actor_id,
            action="RESET_PASSWORD",
            resource="user",
            resource_id=str(user.id),
            after={"employee_code": user.username, "password_reset_at": now.isoformat()},
        )
        return ResetPasswordOutput(employee_code=user.username, password_reset_at=now)
