import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.auth.application.accounts import DEFAULT_EMPLOYEE_PASSWORD
from app.auth.application.use_case import LoginInputDTO, LoginUseCase
from app.auth.domain.entities.user import Role, UserEntity


class FakeUserRepository:
    def __init__(self, user: UserEntity | None):
        self.user = user

    async def find_one(self, *_conditions):
        return self.user

    async def update(self, user: UserEntity) -> UserEntity:
        self.user = user
        return user


class FakeEmployeeRepository:
    async def find_one(self, *_conditions):
        return None


class FakeUnitOfWork:
    def __init__(self, user: UserEntity | None):
        self.user_repository = FakeUserRepository(user)
        self.employee_repository = FakeEmployeeRepository()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return None

    def get_repo(self, entity, _model):
        if entity is UserEntity:
            return self.user_repository
        return self.employee_repository


class FakeSecurityService:
    def __init__(self, password_matches: bool):
        self.password_matches = password_matches

    def verify_password(self, _password: str, _password_hash: str) -> bool:
        return self.password_matches

    def create_access_token(self, _payload: dict) -> str:
        return "test-token"


class LoginAuditTests(unittest.IsolatedAsyncioTestCase):
    def make_user(self, **changes) -> UserEntity:
        user = UserEntity(
            id=uuid4(),
            username="employee-1",
            password_hash="hashed-secret",
            email="employee@example.test",
        )
        return replace(user, **changes)

    async def test_successful_login_is_audited_without_credentials(self):
        user = self.make_user()
        audit = AsyncMock()
        use_case = LoginUseCase(
            FakeUnitOfWork(user),
            FakeSecurityService(password_matches=True),
            audit,
        )
        with patch(
            "app.auth.application.use_case.get_app_role",
            new=AsyncMock(return_value=(Role.USER, ["EMPLOYEE"])),
        ):
            await use_case.execute(LoginInputDTO("employee-1", "secret"))

        audit.record.assert_awaited_once_with(
            user_id=user.id,
            action="LOGIN_SUCCESS",
            resource="authentication",
            resource_id=str(user.id),
            after={"outcome": "success"},
        )
        self.assertNotIn("secret", repr(audit.record.await_args))

    async def test_login_requires_password_change_when_default_password_is_used(self):
        user = self.make_user(password_changed_at=None)
        use_case = LoginUseCase(
            FakeUnitOfWork(user),
            FakeSecurityService(password_matches=True),
            AsyncMock(),
        )
        with patch(
            "app.auth.application.use_case.get_app_role",
            new=AsyncMock(return_value=(Role.USER, ["EMPLOYEE"])),
        ):
            result = await use_case.execute(LoginInputDTO("employee-1", DEFAULT_EMPLOYEE_PASSWORD))

        self.assertTrue(result.must_change_password)

    async def test_login_does_not_require_password_change_when_different_password_is_used(self):
        user = self.make_user(password_changed_at=None)
        use_case = LoginUseCase(
            FakeUnitOfWork(user),
            FakeSecurityService(password_matches=True),
            AsyncMock(),
        )
        with patch(
            "app.auth.application.use_case.get_app_role",
            new=AsyncMock(return_value=(Role.USER, ["EMPLOYEE"])),
        ):
            result = await use_case.execute(LoginInputDTO("employee-1", "employee-chosen-password"))

        self.assertFalse(result.must_change_password)

    async def test_login_requires_password_change_if_default_password_is_used_again(self):
        user = self.make_user(password_changed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        use_case = LoginUseCase(
            FakeUnitOfWork(user),
            FakeSecurityService(password_matches=True),
            AsyncMock(),
        )
        with patch(
            "app.auth.application.use_case.get_app_role",
            new=AsyncMock(return_value=(Role.USER, ["EMPLOYEE"])),
        ):
            result = await use_case.execute(LoginInputDTO("employee-1", DEFAULT_EMPLOYEE_PASSWORD))

        self.assertTrue(result.must_change_password)

    async def test_failed_unknown_user_login_is_audited_without_identifier(self):
        audit = AsyncMock()
        use_case = LoginUseCase(
            FakeUnitOfWork(None),
            FakeSecurityService(password_matches=False),
            audit,
        )

        with self.assertRaisesRegex(ValueError, "Invalid email or password"):
            await use_case.execute(LoginInputDTO("unknown@example.test", "secret"))

        audit.record.assert_awaited_once_with(
            user_id="anonymous",
            action="LOGIN_FAILURE",
            resource="authentication",
            resource_id="anonymous",
            after={"reason": "invalid_credentials"},
        )
        self.assertNotIn("unknown@example.test", repr(audit.record.await_args))
        self.assertNotIn("secret", repr(audit.record.await_args))

    async def test_failed_login_that_triggers_lockout_records_both_events(self):
        user = self.make_user(failed_login_count=1)
        audit = AsyncMock()
        use_case = LoginUseCase(
            FakeUnitOfWork(user),
            FakeSecurityService(password_matches=False),
            audit,
        )
        with patch(
            "app.auth.application.use_case.settings.AUTH_MAX_FAILED_LOGIN_ATTEMPTS",
            2,
        ):
            with self.assertRaisesRegex(ValueError, "Invalid email or password"):
                await use_case.execute(LoginInputDTO("employee-1", "secret"))

        self.assertEqual(audit.record.await_count, 2)
        calls = audit.record.await_args_list
        self.assertEqual(calls[0].kwargs["action"], "LOGIN_FAILURE")
        self.assertEqual(calls[0].kwargs["after"], {"reason": "invalid_credentials"})
        self.assertEqual(calls[1].kwargs["action"], "ACCOUNT_LOCKED")
        self.assertEqual(calls[1].kwargs["resource_id"], str(user.id))
        self.assertEqual(calls[1].kwargs["after"]["failed_attempt_count"], 2)
        self.assertIn("locked_until", calls[1].kwargs["after"])
        self.assertNotIn("secret", repr(calls))


if __name__ == "__main__":
    unittest.main()
