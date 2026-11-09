import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy import true
from sqlalchemy.dialects import postgresql

from app.auth.infrastructure.approval_routing import (
    ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS,
    ApprovalRoutingError,
    OrgUnitApprover,
    approval_route_scope,
    resolve_org_unit_approver,
    save_approval_route,
)
from app.attendance.infrastructure.correction_db_model import AttendanceCorrectionModel
from app.core.database import init_db_models


TODAY = date(2026, 11, 4)


def unit(unit_id, company_id, *, manager_id=None, parent_id=None, **changes):
    values = {
        "id": unit_id,
        "company_id": company_id,
        "manager_employee_id": manager_id,
        "parent_org_unit_id": parent_id,
        "is_active": True,
        "status": "ACTIVE",
        "deleted_at": None,
        "effective_from": date(2026, 1, 1),
        "effective_to": None,
        "manager_is_approver": True,
        "excluded_approval_org_unit_ids": [],
    }
    values.update(changes)
    return SimpleNamespace(**values)


class RoutingSession:
    def __init__(self, assignments, units, *, account=None, has_permission=True):
        self.assignments = assignments
        self.units = units
        self.account = account or uuid4()
        self.has_permission = has_permission
        self.execute = AsyncMock(side_effect=self._execute)
        self.get = AsyncMock(side_effect=lambda model, key: self.units.get(key))
        self.scalar = AsyncMock(return_value=has_permission)
        self.flush = AsyncMock()
        self.add = MagicMock()

    async def _execute(self, statement):
        return SimpleNamespace(all=lambda: self.assignments, scalar_one_or_none=lambda: self.account)


class OrgUnitApproverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        init_db_models()
        self.employee_id = uuid4()
        self.manager_id = uuid4()
        self.parent_manager_id = uuid4()
        self.company_id = uuid4()
        self.unit_id = uuid4()
        self.parent_id = uuid4()

    def session(self, *, child_manager=None, parent_manager=None, **options):
        units = {
            self.unit_id: unit(self.unit_id, self.company_id, manager_id=child_manager, parent_id=self.parent_id),
            self.parent_id: unit(self.parent_id, self.company_id, manager_id=parent_manager),
        }
        return RoutingSession([(self.company_id, self.unit_id)], units, **options)

    async def resolve(self, session, employee_id=None, excluded=frozenset(), permission_code="overtime.approve_team"):
        return await resolve_org_unit_approver(
            session,
            employee_id or self.employee_id,
            TODAY,
            permission_code,
            excluded_employee_ids=excluded,
        )

    async def test_unit_manager_is_selected_and_requires_permission(self):
        session = self.session(child_manager=self.manager_id, parent_manager=self.parent_manager_id)
        result = await self.resolve(session, permission_code="unrelated.permission")
        self.assertEqual(result, OrgUnitApprover(self.manager_id, self.unit_id, self.unit_id))
        permission_query = str(session.scalar.await_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn("role_permissions.allowed", permission_query)
        self.assertIn("permissions.permission_code", permission_query)

    async def test_manager_assignment_grants_team_approvals_without_role_permission(self):
        for permission_code in sorted(ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS):
            with self.subTest(permission_code=permission_code):
                session = self.session(
                    child_manager=self.manager_id, parent_manager=self.parent_manager_id, has_permission=False
                )
                result = await self.resolve(session, permission_code=permission_code)
                self.assertEqual(result.employee_id, self.manager_id)
                session.scalar.assert_not_awaited()

    async def test_self_and_excluded_managers_escalate_to_parent(self):
        for child_manager, excluded in (
            (self.employee_id, frozenset()),
            (self.manager_id, frozenset({self.manager_id})),
        ):
            with self.subTest(child_manager=child_manager):
                result = await self.resolve(
                    self.session(child_manager=child_manager, parent_manager=self.parent_manager_id),
                    excluded=excluded,
                )
                self.assertEqual(result.employee_id, self.parent_manager_id)
                self.assertEqual(result.approver_org_unit_id, self.parent_id)

    async def test_missing_unit_manager_does_not_escalate_to_parent(self):
        session = self.session(parent_manager=self.parent_manager_id)
        with self.assertRaisesRegex(ApprovalRoutingError, "no manager"):
            await self.resolve(session)
        self.assertEqual(session.get.await_count, 1)

    async def test_missing_parent_manager_remains_an_explicit_configuration_error(self):
        session = self.session(child_manager=self.employee_id)
        grandparent_id = uuid4()
        session.units[self.parent_id].parent_org_unit_id = grandparent_id
        session.units[grandparent_id] = unit(grandparent_id, self.company_id, manager_id=self.parent_manager_id)
        with self.assertRaisesRegex(ApprovalRoutingError, "no manager"):
            await self.resolve(session)
        self.assertEqual(session.get.await_count, 2)

    async def test_self_managers_are_skipped_until_an_independent_ancestor(self):
        session = self.session(child_manager=self.employee_id, parent_manager=self.employee_id)
        grandparent_id = uuid4()
        session.units[self.parent_id].parent_org_unit_id = grandparent_id
        session.units[grandparent_id] = unit(grandparent_id, self.company_id, manager_id=self.parent_manager_id)
        result = await self.resolve(session)
        self.assertEqual(result.approver_org_unit_id, grandparent_id)

    async def test_disabled_manager_escalates_for_every_workflow(self):
        for permission in ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS:
            session = self.session(child_manager=self.manager_id, parent_manager=self.parent_manager_id)
            session.units[self.unit_id].manager_is_approver = False
            result = await self.resolve(session, permission_code=permission)
            self.assertEqual(result.employee_id, self.parent_manager_id)

    async def test_disabled_manager_without_parent_is_unresolved(self):
        session = self.session(child_manager=self.manager_id)
        session.units[self.unit_id].manager_is_approver = False
        session.units[self.parent_id].manager_is_approver = False
        with self.assertRaisesRegex(ApprovalRoutingError, "No eligible"):
            await self.resolve(session)

    async def test_exclusion_covers_subtree_but_not_childs_own_manager(self):
        session = self.session(child_manager=self.manager_id, parent_manager=self.parent_manager_id)
        session.units[self.parent_id].excluded_approval_org_unit_ids = [self.unit_id]
        result = await self.resolve(session)
        self.assertEqual(result.employee_id, self.manager_id)
        session.units[self.unit_id].manager_is_approver = False
        with self.assertRaisesRegex(ApprovalRoutingError, "No eligible"):
            await self.resolve(session)

    async def test_excluded_ancestor_is_skipped_and_unrelated_exclusion_does_not_block(self):
        session = self.session(child_manager=self.employee_id, parent_manager=self.parent_manager_id)
        grandparent_id, root_id, root_manager_id = uuid4(), uuid4(), uuid4()
        session.units[self.parent_id].manager_is_approver = False
        session.units[self.parent_id].parent_org_unit_id = grandparent_id
        session.units[grandparent_id] = unit(
            grandparent_id, self.company_id, manager_id=self.manager_id, parent_id=root_id,
            excluded_approval_org_unit_ids=[self.parent_id],
        )
        session.units[root_id] = unit(root_id, self.company_id, manager_id=root_manager_id)
        result = await self.resolve(session)
        self.assertEqual(result.employee_id, root_manager_id)
        session.units[grandparent_id].excluded_approval_org_unit_ids = [uuid4()]
        result = await self.resolve(session)
        self.assertEqual(result.employee_id, self.manager_id)

    async def test_holding_unresolved_requests_logs_and_saves_without_approving(self):
        from app.auth.infrastructure.approval_routing import assign_org_approval
        session = self.session(parent_manager=self.parent_manager_id)
        resource_id = uuid4()
        with self.assertLogs("app.auth.infrastructure.approval_routing", level="WARNING"):
            result = await assign_org_approval(
                session, resource_type="leave_application", resource_id=resource_id,
                employee_id=self.employee_id, assigned_by=uuid4(), on_date=TODAY,
                permission_code="leave.approve_team", hold_unresolved=True,
            )
        self.assertIsNone(result)
        route = session.add.call_args.args[0]
        self.assertEqual(route.routing_mode, "UNRESOLVED")
        self.assertIsNone(route.approver_employee_id)
        self.assertIn("no manager", route.routing_error)

    async def test_missing_ambiguous_or_unassigned_employment_is_explicit(self):
        for assignments, message in (
            ([], "No current employment assignment"),
            ([(self.company_id, None)], "No organization unit"),
            ([(self.company_id, self.unit_id), (self.company_id, self.parent_id)], "Multiple current"),
        ):
            with self.subTest(assignments=assignments):
                with self.assertRaisesRegex(ApprovalRoutingError, message):
                    await self.resolve(RoutingSession(assignments, {}))

    async def test_invalid_hierarchy_or_missing_manager_is_explicit(self):
        scenarios = (
            ({self.unit_id: unit(self.unit_id, self.company_id, manager_id=self.employee_id, parent_id=self.unit_id)}, "cycle"),
            ({self.unit_id: unit(self.unit_id, uuid4())}, "invalid company"),
            ({self.unit_id: unit(self.unit_id, self.company_id, is_active=False)}, "not active"),
            ({self.unit_id: unit(self.unit_id, self.company_id)}, "no manager"),
        )
        for units, message in scenarios:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ApprovalRoutingError, message):
                    await self.resolve(RoutingSession([(self.company_id, self.unit_id)], units))

    async def test_inactive_account_or_missing_permission_is_not_silently_skipped(self):
        session = self.session(child_manager=self.manager_id, parent_manager=self.parent_manager_id)
        session.account = None
        with self.assertRaisesRegex(ApprovalRoutingError, "employee-linked account"):
            await self.resolve(session)
        session = self.session(
            child_manager=self.manager_id, parent_manager=self.parent_manager_id, has_permission=False
        )
        with self.assertRaisesRegex(ApprovalRoutingError, "required approval permission"):
            await self.resolve(session, permission_code="unrelated.permission")

    async def test_saving_archives_previous_route_and_records_snapshot(self):
        session = RoutingSession([], {})
        session.execute = AsyncMock()
        resource_id, actor_id = uuid4(), uuid4()
        approver = OrgUnitApprover(self.manager_id, self.unit_id, self.parent_id)
        await save_approval_route(
            session,
            resource_type="overtime_application",
            resource_id=resource_id,
            employee_id=self.employee_id,
            assigned_by=actor_id,
            approver=approver,
        )
        saved = session.add.call_args.args[0]
        self.assertEqual(saved.routing_mode, "ORG_UNIT")
        self.assertEqual(saved.approver_employee_id, self.manager_id)
        self.assertEqual(saved.source_org_unit_id, self.unit_id)
        self.assertEqual(saved.approver_org_unit_id, self.parent_id)
        session.execute.assert_awaited_once()
        session.flush.assert_awaited_once()

    def test_scope_requires_an_explicit_current_legacy_or_assigned_route(self):
        expression = approval_route_scope(
            "attendance_correction", AttendanceCorrectionModel.id, self.manager_id, true()
        )
        sql = str(expression.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("ORG_UNIT", sql)
        self.assertIn("LEGACY", sql)
        self.assertIn(str(self.manager_id), sql)
        self.assertIn("is_current IS true", sql)


if __name__ == "__main__":
    unittest.main()
