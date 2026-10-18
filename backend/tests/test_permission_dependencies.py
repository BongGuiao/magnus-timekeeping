import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import HTTPException

from app.auth.infrastructure.dependencies import require_any_permission


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
