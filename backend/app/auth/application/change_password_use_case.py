from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from app.auth.application.password_ports import AuditTrail, PasswordHasher, UserAccountUnitOfWork
from app.auth.domain import password_rules as rules
from app.auth.domain.exceptions import AccountNotFoundError, AuthRuleError, InvalidCredentialsError
from app.core.generics.uc_base import BaseUseCase

INCORRECT_CURRENT_PASSWORD = "The current password is incorrect."


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class LockoutPolicy:
    max_attempts: int
    lockout_minutes: int


@dataclass(frozen=True)
class ChangePasswordInput:
    user_id: UUID
    current_password: str
    new_password: str


@dataclass(frozen=True)
class ChangePasswordOutput:
    password_changed_at: datetime


class ChangePasswordUseCase(BaseUseCase[ChangePasswordOutput]):
    """Lets a signed-in user replace their own password after proving they know the current one."""

    def __init__(
        self,
        uow: UserAccountUnitOfWork,
        hasher: PasswordHasher,
        audit: AuditTrail,
        lockout: LockoutPolicy,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self._uow = uow
        self._hasher = hasher
        self._audit = audit
        self._lockout = lockout
        self._clock = clock

    async def _execute(self, data: ChangePasswordInput) -> ChangePasswordOutput:
        now = self._clock()
        rejection: AuthRuleError | None = None
        lockout_event: dict[str, object] | None = None
        async with self._uow as uow:
            user = await uow.users.get_for_update(data.user_id)
            if user is None:
                raise AccountNotFoundError("User account was not found.")

            user = rules.clear_expired_lock(user, now)
            rules.ensure_account_usable(user, now)
            rules.validate_new_password(data.new_password, data.current_password)

            if self._hasher.verify(data.current_password, user.password_hash):
                user = rules.after_password_change(user, self._hasher.hash(data.new_password), now, data.user_id)
            else:
                user = rules.after_failed_password_attempt(
                    user, now, self._lockout.max_attempts, self._lockout.lockout_minutes
                )
                if user.locked_until is not None:
                    lockout_event = {
                        "failed_attempt_count": user.failed_login_count,
                        "locked_until": user.locked_until.isoformat(),
                    }
                rejection = InvalidCredentialsError(INCORRECT_CURRENT_PASSWORD)
            await uow.users.save(user)

        # The failed-attempt counter must be committed, so the rejection is raised after the unit of work exits.
        if rejection is not None:
            await self._audit.record(
                user_id=data.user_id,
                action="CHANGE_PASSWORD_FAILURE",
                resource="authentication",
                resource_id=str(data.user_id),
                after={"reason": "invalid_current_password"},
            )
            if lockout_event is not None:
                await self._audit.record(
                    user_id=data.user_id,
                    action="ACCOUNT_LOCKED",
                    resource="user",
                    resource_id=str(data.user_id),
                    after=lockout_event,
                )
            raise rejection

        await self._audit.record(
            user_id=data.user_id,
            action="CHANGE_PASSWORD",
            resource="user",
            resource_id=str(data.user_id),
            after={"password_changed_at": now.isoformat()},
        )
        return ChangePasswordOutput(password_changed_at=now)
