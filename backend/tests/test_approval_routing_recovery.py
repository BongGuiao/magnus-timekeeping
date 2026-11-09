import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.attendance.infrastructure import approval_routing_router as routing
from app.auth.application.authorization import CurrentAuthorization
from app.auth.infrastructure.approval_routing import ApprovalRoutingError, OrgUnitApprover
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.core.database import init_db_models
from app.filemaintenance.schedule.domain.schedule_upload_exceptions import ScheduleUploadStateError


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        init_db_models()
        self.actor_id, self.employee_id = uuid4(), uuid4()
        self.route = SimpleNamespace(
            id=uuid4(), resource_id=uuid4(), resource_type="leave_application",
            employee_id=self.employee_id, assigned_by=self.actor_id,
            routing_mode="UNRESOLVED", is_current=True, routing_error="Missing manager",
            created_at=datetime.now(timezone.utc),
        )
        self.resource = SimpleNamespace(id=self.route.resource_id, status="PENDING", is_active=True)
        self.session = SimpleNamespace(
            scalar=AsyncMock(return_value=self.route), get=AsyncMock(return_value=self.resource),
            execute=AsyncMock(), scalars=AsyncMock(), flush=AsyncMock(),
        )
        self.uow = Mock()
        self.uow.__aenter__ = AsyncMock(return_value=SimpleNamespace(session=self.session))
        self.uow.__aexit__ = AsyncMock(return_value=False)
        self.audit = patch.object(routing, "log_entity_action", new_callable=AsyncMock).start()
        self.addCleanup(patch.stopall)

    async def recover(self, payload=None):
        return await routing.recover_unresolved_approval(
            self.route.id, payload or routing.RoutingRecoveryInput(),
            claims={"sub": str(self.actor_id)}, uow=self.uow, es_client=None,
        )

    async def test_assigned_and_legacy_routes_cannot_be_recovered(self):
        for mode, current in (("ORG_UNIT", True), ("LEGACY", True), ("UNRESOLVED", False)):
            self.route.routing_mode, self.route.is_current = mode, current
            with self.assertRaises(HTTPException) as error:
                await self.recover()
            self.assertEqual(error.exception.status_code, 409)
        self.session.get.assert_not_awaited()
        self.audit.assert_not_awaited()

    async def test_closed_request_cannot_be_recovered(self):
        self.resource.status = "APPROVED"
        with self.assertRaises(HTTPException) as error:
            await self.recover()
        self.assertEqual(error.exception.status_code, 409)
        self.audit.assert_not_awaited()

    async def test_manual_assignment_requires_a_nonblank_audit_reason(self):
        for reason in (None, "   "):
            with self.assertRaises(HTTPException) as error:
                await self.recover(routing.RoutingRecoveryInput(approver_employee_id=uuid4(), reason=reason))
            self.assertEqual(error.exception.status_code, 422)
        self.session.scalar.assert_not_awaited()

    async def test_retry_keeps_failure_visible_and_audits_it(self):
        with patch.object(routing, "assign_org_approval", new_callable=AsyncMock) as assign:
            assign.side_effect = ApprovalRoutingError("Still no independent parent")
            with self.assertLogs(routing.__name__, level="WARNING"):
                response = await self.recover()
        self.assertEqual(response.data.routing_mode, "UNRESOLVED")
        self.assertEqual(response.data.routing_error, "Still no independent parent")
        self.assertEqual(self.route.routing_error, response.data.routing_error)
        self.assertTrue(self.route.is_current)
        self.audit.assert_awaited_once()

    async def test_successful_retry_assigns_one_reviewer_without_approving(self):
        with patch.object(routing, "assign_org_approval", new_callable=AsyncMock) as assign:
            response = await self.recover()
        self.assertEqual(response.data.routing_mode, "ORG_UNIT")
        self.assertEqual(self.resource.status, "PENDING")
        self.assertEqual(assign.call_args.kwargs["employee_id"], self.employee_id)
        self.assertNotIn("hold_unresolved", assign.call_args.kwargs)
        self.audit.assert_awaited_once()

    async def test_manual_assignment_excludes_assigning_hr_employee_and_saves_snapshot(self):
        hr_employee, manager_id = uuid4(), uuid4()
        self.session.get.side_effect = [self.resource, SimpleNamespace(employee_id=hr_employee)]
        with (
            patch.object(routing, "_manual_approver", new_callable=AsyncMock) as select_manager,
            patch.object(routing, "save_approval_route", new_callable=AsyncMock) as save,
        ):
            select_manager.return_value = OrgUnitApprover(manager_id, uuid4(), uuid4())
            response = await self.recover(routing.RoutingRecoveryInput(
                approver_employee_id=manager_id, reason="Independent cover manager",
            ))
        self.assertEqual(response.data.routing_mode, "ORG_UNIT")
        self.assertIn(hr_employee, select_manager.call_args.args[3])
        self.assertEqual(save.call_args.kwargs["assigned_by"], self.actor_id)
        self.assertEqual(self.resource.status, "PENDING")
        self.assertEqual(self.audit.call_args.kwargs["after"]["reason"], "Independent cover manager")

    async def test_manual_approver_rejects_requester_or_excluded_employee_before_queries(self):
        for employee_id, excluded in ((self.employee_id, set()), (self.actor_id, {self.actor_id})):
            with self.assertRaisesRegex(ApprovalRoutingError, "independent"):
                await routing._manual_approver(
                    self.session, {self.employee_id}, employee_id, excluded, datetime.now(routing.MANILA).date(),
                )
        self.session.scalar.assert_not_awaited()

    async def test_manual_approver_requires_active_source_and_same_company_manager(self):
        manager_id, company_id, source_id = uuid4(), uuid4(), uuid4()
        self.session.execute.return_value = SimpleNamespace(all=lambda: [(company_id, source_id)])
        source = SimpleNamespace(
            company_id=company_id, deleted_at=None, is_active=False, status="ACTIVE",
            effective_from=datetime(2020, 1, 1).date(), effective_to=None,
            parent_org_unit_id=None,
        )
        self.session.get.return_value = source
        self.session.scalar.side_effect = [uuid4()]
        with self.assertRaisesRegex(ApprovalRoutingError, "source org unit"):
            await routing._manual_approver(
                self.session, {self.employee_id}, manager_id, set(), datetime.now(routing.MANILA).date(),
            )
        source.is_active = True
        self.session.scalar.side_effect = [uuid4(), None]
        with self.assertRaisesRegex(ApprovalRoutingError, "every affected company"):
            await routing._manual_approver(
                self.session, {self.employee_id}, manager_id, set(), datetime.now(routing.MANILA).date(),
            )

    async def test_schedule_retry_keeps_mixed_approvers_unresolved(self):
        self.route.resource_type = "schedule_upload_batch"
        self.resource = routing.ScheduleUploadBatchModel(
            id=self.route.resource_id, status="PENDING_APPROVAL", uploaded_by=uuid4(),
        )
        self.session.get.side_effect = [self.resource, SimpleNamespace(employee_id=uuid4())]
        self.session.scalars.return_value = SimpleNamespace(all=lambda: [self.employee_id])
        with patch.object(routing.SqlAlchemyScheduleUploadRepository, "assign_batch_approver", new_callable=AsyncMock) as assign:
            assign.side_effect = ScheduleUploadStateError("Split mixed approvers into separate uploads")
            with self.assertLogs(routing.__name__, level="WARNING"):
                response = await self.recover()
        self.assertEqual(response.data.routing_mode, "UNRESOLVED")
        self.assertIn("Split", response.data.routing_error)

    async def test_schedule_retry_honors_explicit_unresolved_result(self):
        self.route.resource_type = "schedule_upload_batch"
        resource = routing.ScheduleUploadBatchModel(
            id=self.route.resource_id, status="PENDING_APPROVAL", uploaded_by=uuid4(),
        )
        self.session.get.side_effect = [resource, SimpleNamespace(employee_id=None)]
        self.session.scalars.return_value = SimpleNamespace(all=lambda: [self.employee_id])
        with patch.object(routing.SqlAlchemyScheduleUploadRepository, "assign_batch_approver", new_callable=AsyncMock):
            response = await self.recover()
        self.assertEqual(response.data.routing_mode, "UNRESOLVED")
        self.assertEqual(response.data.routing_error, "Missing manager")

    async def test_own_alerts_are_scoped_and_cover_all_seven_pending_resource_types(self):
        self.session.execute.return_value = SimpleNamespace(all=lambda: [])
        authorization = CurrentAuthorization([], [], None, self.employee_id)
        response = await routing.list_unresolved_approvals(
            claims={"sub": str(self.actor_id)}, authorization=authorization, uow=self.uow,
        )
        self.assertFalse(response.data.can_manage)
        self.assertEqual(response.data.approvers, [])
        self.assertEqual(self.session.execute.await_count, 7)
        for call in self.session.execute.call_args_list:
            compiled = call.args[0].compile(dialect=postgresql.dialect())
            sql = str(compiled)
            self.assertIn("assigned_by =", sql)
            self.assertIn(" OR ", sql)
            self.assertIn("is_current IS true", sql)
            self.assertIn("UNRESOLVED", compiled.params.values())
            self.assertIn(self.actor_id, compiled.params.values())
            self.assertIn(self.employee_id, compiled.params.values())

    async def test_hr_lists_all_resources_and_active_manager_options(self):
        empty = SimpleNamespace(all=lambda: [])
        self.session.execute.side_effect = [empty] * 7 + [SimpleNamespace(scalars=lambda: empty)]
        response = await routing.list_unresolved_approvals(
            claims={"sub": str(self.actor_id)},
            authorization=CurrentAuthorization([], ["employees.manage"], None), uow=self.uow,
        )
        self.assertTrue(response.data.can_manage)
        for call in self.session.execute.call_args_list[:7]:
            self.assertNotIn("assigned_by =", str(call.args[0]))
        options_sql = str(self.session.execute.call_args_list[-1].args[0])
        self.assertIn("account_status", options_sql)
        self.assertIn("org_unit", options_sql)


class RecoveryPermissionTests(unittest.TestCase):
    def test_non_hr_cannot_recover_and_routes_are_registered(self):
        app = FastAPI()
        app.include_router(routing.router, prefix="/attendance")
        app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(uuid4())}
        app.dependency_overrides[get_current_authorization_use_case] = lambda: SimpleNamespace(
            execute=AsyncMock(return_value=CurrentAuthorization([], [], None)),
        )
        with TestClient(app) as client:
            response = client.post(f"/attendance/approval-routing/{uuid4()}/recover", json={})
        self.assertEqual(response.status_code, 403)
        self.assertIn("/attendance/approval-routing/unresolved", app.openapi()["paths"])
