import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.auth.application.change_password_use_case import (
    INCORRECT_CURRENT_PASSWORD,
    ChangePasswordInput,
    ChangePasswordUseCase,
    LockoutPolicy,
)
from app.auth.domain import password_rules as rules
from app.auth.domain.entities.user import AccountStatus, UserEntity
from app.auth.domain.exceptions import (
    AccountLockedError,
    AccountNotFoundError,
    AccountUnavailableError,
    InvalidCredentialsError,
    PasswordPolicyError,
)
from app.auth.infrastructure.adapters import Argon2PasswordHasher
from app.auth.infrastructure.password_router import ChangePasswordRequestSchema, change_password

NOW = datetime(2026, 10, 13, 4, tzinfo=timezone.utc)
LOCKOUT = LockoutPolicy(max_attempts=3, lockout_minutes=15)


class FakeHasher:
    """Deterministic stand-in; the real Argon2 round trip is covered separately."""

    def __init__(self):
        self.verify_calls = 0

    def hash(self, plain_password):
        return f"hashed:{plain_password}"

    def verify(self, plain_password, password_hash):
        self.verify_calls += 1
        return password_hash == f"hashed:{plain_password}"


def make_user(**changes) -> UserEntity:
    values = dict(
        id=uuid4(), username="EMP-1", email="ana@example.test", password_hash="hashed:old-password",
        account_status=AccountStatus.ACTIVE.value, is_active=True,
    )
    values.update(changes)
    return UserEntity(**values)


class FakeUsers:
    def __init__(self, user):
        self.user, self.saved = user, []

    async def get_for_update(self, user_id):
        return self.user if self.user and self.user.id == user_id else None

    async def save(self, user):
        self.saved.append(user)
        self.user = user


class FakeUnitOfWork:
    def __init__(self, user):
        self.users = FakeUsers(user)
        self.exit_exception = "not exited"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.exit_exception = exc_type


class PasswordRuleTests(unittest.TestCase):
    def test_new_password_length_and_difference_are_enforced(self):
        rules.validate_new_password("long-enough", "old-password")
        for new, message in (
            ("short", "at least 8"),
            ("x" * (rules.MAX_PASSWORD_LENGTH + 1), "at most 128"),
            ("same-password", "different from the current"),
        ):
            with self.subTest(new=new[:10]), self.assertRaisesRegex(PasswordPolicyError, message):
                rules.validate_new_password(new, "same-password")

    def test_boundary_lengths_are_accepted(self):
        for length in (rules.MIN_PASSWORD_LENGTH, rules.MAX_PASSWORD_LENGTH):
            rules.validate_new_password("x" * length, "old")

    def test_inactive_pending_disabled_and_locked_accounts_are_unusable(self):
        for changes in (
            {"is_active": False}, {"account_status": AccountStatus.DISABLED.value},
            {"account_status": AccountStatus.PENDING.value}, {"account_status": AccountStatus.LOCKED.value},
        ):
            with self.subTest(changes=changes), self.assertRaises(AccountUnavailableError):
                rules.ensure_account_usable(make_user(**changes), NOW)
        rules.ensure_account_usable(make_user(), NOW)

    def test_temporary_lockout_blocks_until_it_expires(self):
        locked = make_user(locked_until=NOW + timedelta(minutes=1), failed_login_count=3)
        with self.assertRaises(AccountLockedError):
            rules.ensure_account_usable(locked, NOW)
        cleared = rules.clear_expired_lock(locked, NOW + timedelta(minutes=1))
        self.assertEqual((cleared.locked_until, cleared.failed_login_count), (None, 0))
        self.assertIs(rules.clear_expired_lock(locked, NOW), locked)

    def test_naive_lock_timestamps_are_treated_as_utc(self):
        naive = make_user(locked_until=(NOW + timedelta(hours=1)).replace(tzinfo=None))
        with self.assertRaises(AccountLockedError):
            rules.ensure_account_usable(naive, NOW)

    def test_failed_attempts_lock_the_account_at_the_threshold(self):
        user = make_user()
        for expected_count, locked in ((1, False), (2, False), (3, True)):
            user = rules.after_failed_password_attempt(user, NOW, 3, 15)
            self.assertEqual(user.failed_login_count, expected_count)
            self.assertEqual(user.locked_until, NOW + timedelta(minutes=15) if locked else None)

    def test_a_password_change_resets_failures_and_stamps_the_change(self):
        actor = uuid4()
        user = make_user(failed_login_count=2, locked_until=None)
        changed = rules.after_password_change(user, "new-hash", NOW, actor)
        self.assertEqual(
            (changed.password_hash, changed.password_changed_at, changed.failed_login_count, changed.updated_by),
            ("new-hash", NOW, 0, actor),
        )


class ChangePasswordUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = make_user()
        self.uow = FakeUnitOfWork(self.user)
        self.hasher = FakeHasher()
        self.audit = MagicMock(record=AsyncMock())
        self.now = NOW
        self.use_case = ChangePasswordUseCase(
            self.uow, self.hasher, self.audit, LOCKOUT, clock=lambda: self.now,
        )

    async def change(self, current="old-password", new="brand-new-password", user_id=None):
        return await self.use_case.execute(ChangePasswordInput(user_id or self.user.id, current, new))

    async def test_success_replaces_the_hash_and_records_an_audit_entry_without_secrets(self):
        self.user = self.uow.users.user = replace(self.user, failed_login_count=2)
        result = await self.change()

        saved = self.uow.users.saved[-1]
        self.assertEqual(saved.password_hash, "hashed:brand-new-password")
        self.assertEqual((saved.password_changed_at, saved.failed_login_count, saved.updated_by), (NOW, 0, self.user.id))
        self.assertEqual(result.password_changed_at, NOW)
        self.assertIsNone(self.uow.exit_exception)

        kwargs = self.audit.record.await_args.kwargs
        self.assertEqual((kwargs["action"], kwargs["resource"], kwargs["user_id"]), ("CHANGE_PASSWORD", "user", self.user.id))
        self.assertEqual(kwargs["after"], {"password_changed_at": NOW.isoformat()})
        self.assertNotIn("password", str(kwargs).replace("CHANGE_PASSWORD", "").replace("password_changed_at", ""))

    async def test_a_wrong_current_password_is_counted_and_committed_not_rolled_back(self):
        with self.assertRaises(InvalidCredentialsError) as error:
            await self.change(current="wrong-password")
        self.assertEqual(str(error.exception), INCORRECT_CURRENT_PASSWORD)
        self.assertEqual(self.uow.users.user.failed_login_count, 1)
        self.assertEqual(self.uow.users.user.password_hash, "hashed:old-password")
        self.assertIsNone(self.uow.exit_exception)  # exited cleanly, so the counter commits
        self.audit.record.assert_awaited_once_with(
            user_id=self.user.id,
            action="CHANGE_PASSWORD_FAILURE",
            resource="authentication",
            resource_id=str(self.user.id),
            after={"reason": "invalid_current_password"},
        )

    async def test_repeated_wrong_passwords_lock_the_account_even_against_the_right_password(self):
        for _ in range(LOCKOUT.max_attempts):
            with self.assertRaises(InvalidCredentialsError):
                await self.change(current="wrong-password")
        self.assertEqual(self.uow.users.user.locked_until, NOW + timedelta(minutes=LOCKOUT.lockout_minutes))
        self.assertEqual(
            [call.kwargs["action"] for call in self.audit.record.await_args_list],
            [
                "CHANGE_PASSWORD_FAILURE",
                "CHANGE_PASSWORD_FAILURE",
                "CHANGE_PASSWORD_FAILURE",
                "ACCOUNT_LOCKED",
            ],
        )

        verifies = self.hasher.verify_calls
        with self.assertRaises(AccountLockedError):
            await self.change()
        self.assertEqual(self.hasher.verify_calls, verifies)  # the password was never even checked
        self.assertEqual(self.uow.users.user.password_hash, "hashed:old-password")

    async def test_the_lockout_expires_and_the_counter_starts_over(self):
        for _ in range(LOCKOUT.max_attempts):
            with self.assertRaises(InvalidCredentialsError):
                await self.change(current="wrong-password")
        self.now = NOW + timedelta(minutes=LOCKOUT.lockout_minutes, seconds=1)
        await self.change()
        self.assertEqual(self.uow.users.user.password_hash, "hashed:brand-new-password")
        self.assertEqual((self.uow.users.user.failed_login_count, self.uow.users.user.locked_until), (0, None))

    async def test_policy_violations_do_not_count_as_failed_attempts_or_touch_the_account(self):
        for new in ("short", "old-password"):
            with self.subTest(new=new), self.assertRaises(PasswordPolicyError):
                await self.change(new=new)
        self.assertEqual(self.uow.users.saved, [])
        self.assertEqual(self.uow.users.user.failed_login_count, 0)
        self.assertEqual(self.hasher.verify_calls, 0)
        self.assertIs(self.uow.exit_exception, PasswordPolicyError)  # rolled back
        self.audit.record.assert_not_awaited()

    async def test_unusable_accounts_are_refused_without_checking_the_password(self):
        for changes in ({"account_status": AccountStatus.PENDING.value}, {"is_active": False}):
            with self.subTest(changes=changes):
                self.uow.users.user = replace(self.user, **changes)
                with self.assertRaises(AccountUnavailableError):
                    await self.change()
        self.assertEqual(self.hasher.verify_calls, 0)

    async def test_unknown_account_is_not_found(self):
        with self.assertRaises(AccountNotFoundError):
            await self.change(user_id=uuid4())

    async def test_the_real_argon2_hasher_round_trips(self):
        hasher = Argon2PasswordHasher()
        user = replace(self.user, password_hash=hasher.hash("old-password"))
        uow = FakeUnitOfWork(user)
        use_case = ChangePasswordUseCase(uow, hasher, self.audit, LOCKOUT, clock=lambda: NOW)
        await use_case.execute(ChangePasswordInput(user.id, "old-password", "brand-new-password"))
        new_hash = uow.users.user.password_hash
        self.assertTrue(new_hash.startswith("$argon2"))
        self.assertTrue(hasher.verify("brand-new-password", new_hash))
        self.assertFalse(hasher.verify("old-password", new_hash))


class ChangePasswordRouterTests(unittest.IsolatedAsyncioTestCase):
    def request(self, **changes):
        return ChangePasswordRequestSchema(**{"current_password": "old-password", "new_password": "brand-new-password", **changes})

    def test_request_schema_enforces_the_same_length_limits(self):
        for changes in (
            {"new_password": "short"}, {"new_password": "x" * 129}, {"current_password": ""},
            {"current_password": "x" * 129},
        ):
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                self.request(**changes)

    async def test_success_passes_the_callers_own_identity_and_returns_the_timestamp(self):
        user_id = uuid4()
        use_case = MagicMock(execute=AsyncMock(return_value=MagicMock(password_changed_at=NOW)))
        response = await change_password(self.request(), claims={"sub": str(user_id)}, use_case=use_case)
        data = use_case.execute.await_args.args[0]
        self.assertEqual((data.user_id, data.current_password, data.new_password), (user_id, "old-password", "brand-new-password"))
        self.assertEqual((response.data.message, response.data.password_changed_at), ("Your password has been changed.", NOW))

    async def test_domain_errors_map_to_http_statuses(self):
        for error, status_code in (
            (InvalidCredentialsError("wrong"), 400), (PasswordPolicyError("weak"), 422),
            (AccountUnavailableError("inactive"), 403), (AccountLockedError("later"), 429),
            (AccountNotFoundError("gone"), 404),
        ):
            with self.subTest(error=type(error).__name__):
                use_case = MagicMock(execute=AsyncMock(side_effect=error))
                with self.assertRaises(HTTPException) as raised:
                    await change_password(self.request(), claims={"sub": str(uuid4())}, use_case=use_case)
                self.assertEqual((raised.exception.status_code, raised.exception.detail), (status_code, str(error)))

    async def test_a_token_without_a_valid_subject_is_unauthorized(self):
        use_case = MagicMock(execute=AsyncMock())
        for claims in ({}, {"sub": "not-a-uuid"}):
            with self.subTest(claims=claims), self.assertRaises(HTTPException) as raised:
                await change_password(self.request(), claims=claims, use_case=use_case)
            self.assertEqual(raised.exception.status_code, 401)
        use_case.execute.assert_not_awaited()
