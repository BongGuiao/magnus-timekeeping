from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from app.auth.domain.entities.user import AccountStatus, UserEntity
from app.auth.domain.exceptions import (
    AccountLockedError,
    AccountUnavailableError,
    PasswordPolicyError,
)

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def validate_new_password(new_password: str, current_password: str) -> None:
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"The new password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(new_password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"The new password must be at most {MAX_PASSWORD_LENGTH} characters long.")
    if new_password == current_password:
        raise PasswordPolicyError("The new password must be different from the current password.")


def clear_expired_lock(user: UserEntity, now: datetime) -> UserEntity:
    """A temporary lockout that has run out no longer counts against the account."""
    if user.locked_until is not None and _as_utc(user.locked_until) <= now:
        return replace(user, locked_until=None, failed_login_count=0)
    return user


def ensure_account_usable(user: UserEntity, now: datetime) -> None:
    if not user.is_active or user.account_status == AccountStatus.DISABLED.value:
        raise AccountUnavailableError("User account is inactive.")
    if user.account_status == AccountStatus.PENDING.value:
        raise AccountUnavailableError("User account is pending activation.")
    if user.account_status == AccountStatus.LOCKED.value:
        raise AccountUnavailableError("User account is locked. Please contact your administrator.")
    if user.locked_until is not None and _as_utc(user.locked_until) > now:
        raise AccountLockedError("Too many failed attempts. Please try again later.")


def after_failed_password_attempt(
    user: UserEntity, now: datetime, max_attempts: int, lockout_minutes: int
) -> UserEntity:
    """Counts a wrong password against the same lockout policy as sign-in."""
    failed_count = (user.failed_login_count or 0) + 1
    locked_until: Optional[datetime] = None
    if failed_count >= max_attempts:
        locked_until = now + timedelta(minutes=lockout_minutes)
    return replace(user, failed_login_count=failed_count, locked_until=locked_until)


def after_password_change(
    user: UserEntity, new_password_hash: str, now: datetime, actor_id: UUID
) -> UserEntity:
    return replace(
        user,
        password_hash=new_password_hash,
        password_changed_at=now,
        failed_login_count=0,
        locked_until=None,
        updated_by=actor_id,
    )
