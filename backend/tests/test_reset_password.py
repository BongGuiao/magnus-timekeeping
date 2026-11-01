import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import HTTPException

from app.auth.application.accounts import DEFAULT_EMPLOYEE_PASSWORD
from app.auth.application.reset_password_use_case import ResetPasswordInput, ResetPasswordToDefaultUseCase
from app.auth.domain.entities.user import AccountStatus, UserEntity, is_system_admin
from app.auth.domain.exceptions import AccountNotFoundError
from app.auth.infrastructure.dependencies import require_system_admin

NOW = datetime(2026, 10, 31, 7, tzinfo=timezone.utc)


class FakeHasher:
    def hash(self, plain_password):
        return f"hashed:{plain_password}"

    def verify(self, plain_password, password_hash):
        return password_hash == f"hashed:{plain_password}"


class FakeUsers:
    def __init__(self, user):
        self.user, self.saved, self.looked_up = user, [], []

    async def get_by_username_for_update(self, username):
        self.looked_up.append(username)
        if self.user and self.user.username.lower() == username.strip().lower():
            return self.user
        return None

    async def save(self, user):
        self.saved.append(user)
        self.user = user


class FakeUnitOfWork:
    def __init__(self, user):
        self.users = FakeUsers(user)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


def make_user(**changes) -> UserEntity:
    values = dict(
        id=uuid4(), username="EMP-0006", email="ana@example.test", password_hash="hashed:secret-password",
        account_status=AccountStatus.ACTIVE.value, is_active=True,
        password_changed_at=NOW - timedelta(days=3), failed_login_count=4,
        locked_until=NOW + timedelta(minutes=10),
    )
    values.update(changes)
    return UserEntity(**values)


class ResetPasswordUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_resets_to_default_clears_lockout_and_forces_change(self):
        actor_id = uuid4()
        uow = FakeUnitOfWork(make_user())
        audit = AsyncMock()
        use_case = ResetPasswordToDefaultUseCase(uow, FakeHasher(), audit, clock=lambda: NOW)

        result = await use_case.execute(ResetPasswordInput(actor_id=actor_id, employee_code="  emp-0006 "))

        saved = uow.users.saved[-1]
        self.assertEqual(saved.password_hash, f"hashed:{DEFAULT_EMPLOYEE_PASSWORD}")
        self.assertEqual(DEFAULT_EMPLOYEE_PASSWORD, "Default123!")
        self.assertIsNone(saved.password_changed_at)
        self.assertEqual((saved.failed_login_count, saved.locked_until), (0, None))
        self.assertEqual(saved.updated_by, actor_id)
        self.assertEqual((result.employee_code, result.password_reset_at), ("EMP-0006", NOW))
        audit.record.assert_awaited_once()
        self.assertEqual(audit.record.await_args.kwargs["action"], "RESET_PASSWORD")
        self.assertEqual(audit.record.await_args.kwargs["user_id"], actor_id)

    async def test_unknown_or_blank_employee_code_is_rejected(self):
        for code in ("EMP-9999", "   "):
            uow = FakeUnitOfWork(make_user())
            audit = AsyncMock()
            use_case = ResetPasswordToDefaultUseCase(uow, FakeHasher(), audit, clock=lambda: NOW)
            with self.subTest(code=code), self.assertRaises(AccountNotFoundError):
                await use_case.execute(ResetPasswordInput(actor_id=uuid4(), employee_code=code))
            self.assertEqual(uow.users.saved, [])
            audit.record.assert_not_awaited()


class RequireSystemAdminTests(unittest.IsolatedAsyncioTestCase):
    async def _check(self, role_codes, claims=None):
        use_case = AsyncMock()
        use_case.execute.return_value = SimpleNamespace(role_codes=role_codes)
        return await require_system_admin(claims or {"sub": str(uuid4())}, use_case)

    async def test_only_system_admin_roles_are_allowed(self):
        for role_codes in (["SYSTEM_ADMIN"], ["EMPLOYEE", "SYSTEM_ADMINISTRATOR"]):
            with self.subTest(role_codes=role_codes):
                self.assertIn("sub", await self._check(role_codes))
        for role_codes in (["HR_ADMIN"], ["EMPLOYEE"], []):
            with self.subTest(role_codes=role_codes), self.assertRaises(HTTPException) as raised:
                await self._check(role_codes)
            self.assertEqual(raised.exception.status_code, 403)

    async def test_invalid_token_subject_is_unauthorized(self):
        with self.assertRaises(HTTPException) as raised:
            await self._check(["SYSTEM_ADMIN"], claims={"sub": "not-a-uuid"})
        self.assertEqual(raised.exception.status_code, 401)

    def test_is_system_admin_normalizes_codes(self):
        self.assertTrue(is_system_admin([" system_admin "]))
        self.assertFalse(is_system_admin(["HR_ADMIN", "EMPLOYEE"]))


if __name__ == "__main__":
    unittest.main()
