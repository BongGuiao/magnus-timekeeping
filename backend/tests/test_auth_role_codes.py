import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi import HTTPException

from app.attendance.infrastructure.clock_policy import AttendanceClockPolicy
from app.auth.application.use_case import _build_token_payload
from app.auth.domain.entities.user import Role, UserEntity, resolve_app_role
from app.auth.infrastructure.dependencies import require_admin_or_kiosk_employee
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
            must_change_password=True,
        )

        self.assertEqual(response.model_dump()["role_code"], role_codes)
        self.assertTrue(response.must_change_password)

    @patch(
        "app.auth.infrastructure.dependencies.resolve_attendance_clock_policy",
        return_value=AttendanceClockPolicy("kiosk", False, "192.168.1.10"),
    )
    def test_employee_role_can_search_from_authorized_kiosk(self, _resolve_policy) -> None:
        claims = {"role": Role.USER.value}

        self.assertIs(
            require_admin_or_kiosk_employee(None, claims, None),
            claims,
        )

    @patch(
        "app.auth.infrastructure.dependencies.resolve_attendance_clock_policy",
        return_value=AttendanceClockPolicy("desktop", True, "192.168.1.10"),
    )
    def test_employee_role_cannot_search_outside_kiosk(self, _resolve_policy) -> None:
        with self.assertRaises(HTTPException) as error:
            require_admin_or_kiosk_employee(None, {"role": Role.USER.value}, None)

        self.assertEqual(error.exception.status_code, 403)

    @patch("app.auth.infrastructure.dependencies.resolve_attendance_clock_policy")
    def test_admin_can_search_outside_kiosk(self, resolve_policy) -> None:
        claims = {"role": Role.ADMIN.value}

        self.assertIs(
            require_admin_or_kiosk_employee(None, claims, None),
            claims,
        )
        resolve_policy.assert_not_called()
