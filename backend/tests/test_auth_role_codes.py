import unittest
from uuid import uuid4

from app.auth.application.use_case import _build_token_payload
from app.auth.domain.entities.user import Role, UserEntity, resolve_app_role
from app.auth.infrastructure.router import TokenResponseSchema


class AuthRoleCodesTests(unittest.TestCase):
    def test_token_payload_includes_all_role_codes(self) -> None:
        role_codes = ["EMPLOYEE", "SYSTEM_ADMINISTRATOR"]
        user = UserEntity(
            id=uuid4(),
            username="employee-1",
            password_hash="hashed",
        )

        payload = _build_token_payload(user, Role.ADMIN, role_codes)

        self.assertEqual(payload["roles"], role_codes)
        self.assertEqual(payload["role_codes"], role_codes)
        self.assertEqual(resolve_app_role(role_codes), Role.ADMIN)

    def test_token_response_schema_exposes_role_codes(self) -> None:
        role_codes = ["EMPLOYEE", "SYSTEM_ADMINISTRATOR"]
        response = TokenResponseSchema(
            access_token="token",
            role="admin",
            role_code=role_codes,
            expires_in_hours=12,
            token_type="bearer",
            employee_name="Employee One",
        )

        self.assertEqual(response.model_dump()["role_code"], role_codes)
