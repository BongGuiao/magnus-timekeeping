import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import HTTPException

from app.auth.infrastructure.dependencies import require_any_permission, require_approval_permission


class PermissionDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_any_permission_allows_employee_leave_submission(self):
        claims = {"sub": str(uuid4())}
        use_case = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(permission_codes=["leave.submit"]))
        )
        permission_checker = require_any_permission("leave.manage", "leave.submit")

        result = await permission_checker(claims, use_case)

        self.assertIs(result, claims)
        use_case.execute.assert_awaited_once()

    async def test_any_permission_rejects_when_none_are_granted(self):
        claims = {"sub": str(uuid4())}
        use_case = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(permission_codes=["leave.read_own"]))
        )
        permission_checker = require_any_permission("leave.manage", "leave.submit")

        with self.assertRaises(HTTPException) as error:
            await permission_checker(claims, use_case)

        self.assertEqual(error.exception.status_code, 403)

    async def test_approval_scope_uses_current_roles_for_verified_employee(self):
        employee_id = uuid4()
        claims = {
            "sub": str(uuid4()), "employee_id": str(employee_id),
            "role": "admin", "role_codes": ["HR_ADMIN"],
        }
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            permission_codes=["leave.approve_team"], role_codes=["SUPERVISOR"], employee_id=employee_id,
        )))
        result = await require_approval_permission("leave.approve_team")(claims, authorization)
        self.assertEqual(result["role"], "user")
        self.assertEqual(result["role_codes"], ["SUPERVISOR"])

    async def test_approval_scope_rejects_stale_employee_link(self):
        claims = {"sub": str(uuid4()), "employee_id": str(uuid4())}
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            permission_codes=["leave.approve_team"], role_codes=["SUPERVISOR"], employee_id=uuid4(),
        )))
        with self.assertRaises(HTTPException) as error:
            await require_approval_permission("leave.approve_team")(claims, authorization)
        self.assertEqual(error.exception.status_code, 403)
        self.assertIn("Sign in again", error.exception.detail)

    async def test_approval_scope_rejects_inactive_employee_profile(self):
        claims = {"sub": str(uuid4()), "employee_id": str(uuid4())}
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            permission_codes=["leave.approve_team"], role_codes=["SUPERVISOR"], employee_id=None,
        )))
        with self.assertRaises(HTTPException) as error:
            await require_approval_permission("leave.approve_team")(claims, authorization)
        self.assertEqual(error.exception.status_code, 403)

    async def test_approval_scope_denies_a_revoked_permission_even_with_old_role_claims(self):
        claims = {"sub": str(uuid4()), "role_codes": ["HR_ADMIN"]}
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            permission_codes=[], role_codes=["EMPLOYEE"], employee_id=None,
        )))
        with self.assertRaises(HTTPException) as error:
            await require_approval_permission("leave.approve_team")(claims, authorization)
        self.assertEqual(error.exception.status_code, 403)

    async def test_approval_scope_accepts_current_admin_without_employee_profile(self):
        claims = {"sub": str(uuid4()), "employee_id": None}
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            permission_codes=["schedule.approve"], role_codes=["HR_ADMIN"], employee_id=None,
        )))
        result = await require_approval_permission("schedule.approve")(claims, authorization)
        self.assertEqual(result["role"], "admin")
        self.assertIsNone(result["employee_id"])
