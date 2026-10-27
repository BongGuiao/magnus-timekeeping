import unittest
from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.auth.domain.entities.user import UserRoleEntity
from app.filemaintenance.employees.application.use_case import direct_report_conditions
from app.filemaintenance.employees.infrastructure.related_router import (
    ensure_payroll_group_change_allowed,
)
from app.filemaintenance.employees.infrastructure.router import resolve_employee_read_scope
from app.filemaintenance.roles.application.payroll_access import (
    PayrollAccessViolationError,
    ensure_role_permission_change_allowed,
    is_restricted_payroll_permission,
)
from app.filemaintenance.roles.application.use_case import (
    CreateUserRoleUseCase,
    UpdateUserRoleUseCase,
    UserRoleOverlapError,
)

ROLE_USE_CASE_MODULE = "app.filemaintenance.roles.application.use_case"


class _FakeUserRoleRepo:
    def __init__(self, existing: UserRoleEntity | None = None):
        self.existing = existing

    async def add(self, payload):
        return UserRoleEntity(**payload)

    async def find_one(self, *_criteria):
        return self.existing

    async def update(self, entity):
        return entity


class _FakeRoleSession:
    def __init__(self, scalar_result=None):
        self.scalar_result = scalar_result

    async def scalar(self, *_args, **_kwargs):
        return self.scalar_result


class _FakeUnitOfWork:
    def __init__(
        self,
        existing: UserRoleEntity | None = None,
        overlapping_assignment_id=None,
    ):
        self.session = _FakeRoleSession(overlapping_assignment_id)
        self.repo = _FakeUserRoleRepo(existing)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get_repo(self, *_args):
        return self.repo


class RolePermissionPayrollGuardTests(unittest.TestCase):
    def test_self_service_payroll_codes_are_not_restricted(self):
        self.assertFalse(is_restricted_payroll_permission("payroll.read_own"))
        self.assertFalse(is_restricted_payroll_permission("payroll.acknowledge_team"))
        self.assertTrue(is_restricted_payroll_permission("payroll.manage"))
        self.assertTrue(is_restricted_payroll_permission("payroll.approve"))
        self.assertFalse(is_restricted_payroll_permission("employees.read"))

    def test_system_admin_role_cannot_receive_any_payroll_permission(self):
        with self.assertRaises(PayrollAccessViolationError):
            ensure_role_permission_change_allowed(
                "SYSTEM_ADMIN", {"system.manage"}, {"system.manage", "payroll.read_own"}
            )

    def test_adding_restricted_payroll_permission_to_any_role_is_rejected(self):
        with self.assertRaises(PayrollAccessViolationError):
            ensure_role_permission_change_allowed(
                "SUPERVISOR", {"employees.read_team"}, {"employees.read_team", "payroll.manage"}
            )

    def test_removing_restricted_payroll_permission_is_rejected(self):
        with self.assertRaises(PayrollAccessViolationError):
            ensure_role_permission_change_allowed(
                "HR_ADMIN", {"payroll.manage", "employees.read"}, {"employees.read"}
            )

    def test_non_payroll_changes_preserving_payroll_grants_are_allowed(self):
        ensure_role_permission_change_allowed(
            "HR_ADMIN",
            {"payroll.manage", "employees.read"},
            {"payroll.manage", "employees.read", "employees.manage"},
        )
        ensure_role_permission_change_allowed(
            "SYSTEM_ADMIN", {"system.manage"}, {"system.manage", "employees.manage"}
        )


class UserRoleSelfAssignmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_cannot_create_overlapping_role_assignment(self):
        payload = {
            "user_id": uuid4(),
            "role_id": uuid4(),
            "effective_from": date(2026, 4, 1),
            "effective_to": date(2026, 12, 31),
        }
        with self.assertRaises(UserRoleOverlapError):
            await CreateUserRoleUseCase(
                _FakeUnitOfWork(overlapping_assignment_id=uuid4())
            ).execute(payload)

    async def test_admin_cannot_assign_payroll_role_to_self(self):
        actor_id = uuid4()
        payload = {
            "user_id": actor_id,
            "role_id": uuid4(),
            "effective_from": date(2026, 1, 1),
            "assigned_by": actor_id,
        }
        with patch(
            f"{ROLE_USE_CASE_MODULE}.role_grants_restricted_payroll",
            AsyncMock(return_value=True),
        ):
            with self.assertRaises(PayrollAccessViolationError):
                await CreateUserRoleUseCase(_FakeUnitOfWork()).execute(payload)

    async def test_admin_can_assign_payroll_role_to_other_user(self):
        payload = {
            "user_id": uuid4(),
            "role_id": uuid4(),
            "effective_from": date(2026, 1, 1),
            "assigned_by": uuid4(),
        }
        with patch(
            f"{ROLE_USE_CASE_MODULE}.role_grants_restricted_payroll",
            AsyncMock(return_value=True),
        ):
            result = await CreateUserRoleUseCase(_FakeUnitOfWork()).execute(payload)
        self.assertEqual(result.user_id, payload["user_id"])

    async def test_admin_can_self_assign_non_payroll_role(self):
        actor_id = uuid4()
        payload = {
            "user_id": actor_id,
            "role_id": uuid4(),
            "effective_from": date(2026, 1, 1),
            "assigned_by": actor_id,
        }
        with patch(
            f"{ROLE_USE_CASE_MODULE}.role_grants_restricted_payroll",
            AsyncMock(return_value=False),
        ):
            result = await CreateUserRoleUseCase(_FakeUnitOfWork()).execute(payload)
        self.assertEqual(result.user_id, actor_id)

    async def test_admin_cannot_extend_own_payroll_role(self):
        actor_id = uuid4()
        existing = UserRoleEntity(
            id=uuid4(),
            user_id=actor_id,
            role_id=uuid4(),
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 6, 30),
        )
        with patch(
            f"{ROLE_USE_CASE_MODULE}.role_grants_restricted_payroll",
            AsyncMock(return_value=True),
        ):
            with self.assertRaises(PayrollAccessViolationError):
                await UpdateUserRoleUseCase(_FakeUnitOfWork(existing)).execute(
                    existing.id, {"effective_to": None}, actor_id
                )

    async def test_admin_can_end_own_payroll_role_early(self):
        actor_id = uuid4()
        existing = UserRoleEntity(
            id=uuid4(),
            user_id=actor_id,
            role_id=uuid4(),
            effective_from=date(2026, 1, 1),
        )
        with patch(
            f"{ROLE_USE_CASE_MODULE}.role_grants_restricted_payroll",
            AsyncMock(return_value=True),
        ):
            result = await UpdateUserRoleUseCase(_FakeUnitOfWork(existing)).execute(
                existing.id,
                {
                    "role_id": existing.role_id,
                    "effective_from": existing.effective_from,
                    "effective_to": date(2026, 3, 31),
                },
                actor_id,
            )
        self.assertEqual(result.effective_to, date(2026, 3, 31))

    async def test_admin_cannot_move_payroll_role_onto_self(self):
        actor_id = uuid4()
        existing = UserRoleEntity(
            id=uuid4(),
            user_id=uuid4(),
            role_id=uuid4(),
            effective_from=date(2026, 1, 1),
        )
        with patch(
            f"{ROLE_USE_CASE_MODULE}.role_grants_restricted_payroll",
            AsyncMock(return_value=True),
        ):
            with self.assertRaises(PayrollAccessViolationError):
                await UpdateUserRoleUseCase(_FakeUnitOfWork(existing)).execute(
                    existing.id, {"user_id": actor_id}, actor_id
                )


class EmployeeReadScopeTests(unittest.TestCase):
    def test_org_wide_read_returns_no_scope(self):
        self.assertIsNone(
            resolve_employee_read_scope({"employee_id": str(uuid4())}, ["employees.read", "employees.read_team"])
        )

    def test_team_read_returns_supervisor_employee_id(self):
        employee_id = uuid4()
        self.assertEqual(
            resolve_employee_read_scope({"employee_id": str(employee_id)}, ["employees.read_team"]),
            employee_id,
        )

    def test_team_read_without_linked_employee_is_forbidden(self):
        with self.assertRaises(HTTPException) as context:
            resolve_employee_read_scope({"employee_id": None}, ["employees.read_team"])
        self.assertEqual(context.exception.status_code, 403)

    def test_no_employee_read_permission_is_forbidden(self):
        with self.assertRaises(HTTPException) as context:
            resolve_employee_read_scope({"employee_id": str(uuid4())}, ["attendance.read_own"])
        self.assertEqual(context.exception.status_code, 403)

    def test_direct_report_condition_filters_by_supervisor(self):
        (condition,) = direct_report_conditions(uuid4(), date(2026, 5, 1))
        sql = str(condition.compile(compile_kwargs={"literal_binds": False}))
        self.assertIn("supervisor_employee_id", sql)
        self.assertIn("separation_date", sql)


class AssignmentPayrollGroupGuardTests(unittest.TestCase):
    def test_non_payroll_user_cannot_set_payroll_group(self):
        with self.assertRaises(HTTPException) as context:
            ensure_payroll_group_change_allowed(
                {"employees.manage"}, {"payroll_group_id": str(uuid4())}
            )
        self.assertEqual(context.exception.status_code, 403)

    def test_non_payroll_user_cannot_change_payroll_group(self):
        with self.assertRaises(HTTPException):
            ensure_payroll_group_change_allowed(
                {"employees.manage"}, {"payroll_group_id": None}, uuid4()
            )

    def test_non_payroll_user_may_omit_or_keep_payroll_group(self):
        existing = uuid4()
        ensure_payroll_group_change_allowed({"employees.manage"}, {"position_title": "Clerk"}, existing)
        ensure_payroll_group_change_allowed({"employees.manage"}, {"payroll_group_id": str(existing)}, existing)
        ensure_payroll_group_change_allowed({"employees.manage"}, {"payroll_group_id": ""})

    def test_payroll_manager_can_set_payroll_group(self):
        ensure_payroll_group_change_allowed(
            {"employees.manage", "payroll.manage"}, {"payroll_group_id": str(uuid4())}, uuid4()
        )


if __name__ == "__main__":
    unittest.main()
