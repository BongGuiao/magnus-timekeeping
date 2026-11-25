import unittest
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import FastAPI
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.auth.application.authorization import CurrentAuthorization
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.filemaintenance.employees.infrastructure.dependencies import get_employee_use_case
from app.filemaintenance.schedule.domain.entities.employee_schedule_assignment import EmployeeScheduleAssignmentEntity
from app.filemaintenance.schedule.domain.entities.rest_day_pattern import RestDayPatternDayEntity, RestDayPatternEntity
from app.filemaintenance.schedule.domain.entities.schedule_template import ScheduleTemplateEntity
from app.filemaintenance.schedule.infrastructure import employee_schedule_assignment_router as routing


class SupervisorScheduleAccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor, self.supervisor, self.employee, self.other, self.template = (uuid4() for _ in range(5))
        self.record = EmployeeScheduleAssignmentEntity(
            id=uuid4(), employee_id=self.employee, schedule_template_id=self.template,
            assignment_type="REGULAR", effective_from=date(2026, 1, 1),
        )
        self.authorization = CurrentAuthorization(
            ["SUPERVISOR"], ["schedule.manage_team"], None, self.supervisor,
        )
        self.claims = {"sub": str(self.actor), "email": "test@example.com", "role": "user"}
        self.auth = SimpleNamespace(execute=AsyncMock(side_effect=lambda _: self.authorization))
        self.employees = SimpleNamespace(execute=AsyncMock(
            side_effect=lambda employee_id, supervisor_id: object()
            if employee_id == self.employee and supervisor_id == self.supervisor else None,
        ))
        self.get = SimpleNamespace(execute=AsyncMock(return_value=self.record))
        self.list = SimpleNamespace(execute=AsyncMock(return_value=[self.record]))
        self.create = SimpleNamespace(execute=AsyncMock(return_value=self.record))
        self.update = SimpleNamespace(execute=AsyncMock(return_value=self.record))
        self.deactivate = SimpleNamespace(execute=AsyncMock(return_value=self.record))
        self.approve = SimpleNamespace(execute=AsyncMock(return_value=self.record))
        self.options = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(
            has_current_assignment=True,
            templates=[SimpleNamespace(id=self.template)],
            patterns=[],
        )))
        self.app = FastAPI()
        self.app.include_router(routing.router)
        self.app.dependency_overrides.update({
            get_current_user_claims: lambda: self.claims,
            get_current_authorization_use_case: lambda: self.auth,
            get_employee_use_case: lambda: self.employees,
            routing.get_employee_schedule_assignment_use_case: lambda: self.get,
            routing.get_list_employee_schedule_assignments_use_case: lambda: self.list,
            routing.get_create_employee_schedule_assignment_use_case: lambda: self.create,
            routing.get_update_employee_schedule_assignment_use_case: lambda: self.update,
            routing.get_deactivate_employee_schedule_assignment_use_case: lambda: self.deactivate,
            routing.get_approve_employee_schedule_assignment_use_case: lambda: self.approve,
            routing._options_dependencies: lambda: self.options,
            get_audit_es_client: lambda: None,
        })
        self.audit = patch.object(routing, "log_entity_action", new_callable=AsyncMock).start()
        self.addCleanup(patch.stopall)

    async def request(self, method, path, body=None, query=""):
        encoded = json.dumps(body).encode() if body is not None else b""
        messages = []
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": encoded, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        await self.app({
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
            "query_string": query.encode(), "headers": [(b"content-type", b"application/json")],
            "server": ("test", 80), "client": ("test", 1234), "root_path": "",
        }, receive, send)
        return next(message["status"] for message in messages if message["type"] == "http.response.start")

    def payload(self, employee=None, template=None):
        return {
            "employee_id": str(employee or self.employee),
            "schedule_template_id": str(template or self.template),
            "assignment_type": "REGULAR",
            "effective_from": "2026-01-01",
        }

    async def test_supervisor_can_manage_direct_report_without_approval_rights(self):
        base = "/employee-schedule-assignments"
        self.assertEqual(await self.request("GET", f"{base}/list", query=f"employee_id={self.employee}"), 200)
        self.assertEqual(await self.request("POST", f"{base}/create", self.payload()), 201)
        self.assertEqual(await self.request("PUT", f"{base}/{self.record.id}", {"reason": "Changed"}), 200)
        self.assertEqual(await self.request("DELETE", f"{base}/{self.record.id}"), 200)
        self.assertEqual(await self.request("POST", f"{base}/{self.record.id}/approve"), 403)
        self.approve.execute.assert_not_awaited()

    async def test_other_employees_and_unscoped_listing_are_denied(self):
        base = "/employee-schedule-assignments"
        self.assertEqual(await self.request("GET", f"{base}/list"), 403)
        self.assertEqual(await self.request("GET", f"{base}/list", query=f"employee_id={self.other}"), 403)
        self.assertEqual(await self.request("POST", f"{base}/create", self.payload(employee=self.other)), 403)
        self.record.employee_id = self.other
        self.assertEqual(await self.request("GET", f"{base}/{self.record.id}"), 403)
        self.assertEqual(await self.request("PUT", f"{base}/{self.record.id}", {"reason": "Changed"}), 403)
        self.assertEqual(await self.request("DELETE", f"{base}/{self.record.id}"), 403)
        self.assertEqual(await self.request("GET", f"{base}/team-options/{self.other}"), 403)
        self.create.execute.assert_not_awaited()
        self.update.execute.assert_not_awaited()
        self.deactivate.execute.assert_not_awaited()

    async def test_employee_transfer_and_unavailable_template_are_denied(self):
        base = "/employee-schedule-assignments"
        self.assertEqual(
            await self.request("PUT", f"{base}/{self.record.id}", {"employee_id": str(self.other)}), 403,
        )
        self.assertEqual(await self.request("POST", f"{base}/create", self.payload(template=uuid4())), 422)
        self.update.execute.assert_not_awaited()
        self.create.execute.assert_not_awaited()

    async def test_account_without_team_permission_is_denied(self):
        self.authorization = CurrentAuthorization(["SUPERVISOR"], [], None, self.supervisor)
        response = await self.request(
            "GET", "/employee-schedule-assignments/list", query=f"employee_id={self.employee}",
        )
        self.assertEqual(response, 403)
        self.list.execute.assert_not_awaited()

    async def test_team_options_load_for_direct_report(self):
        self.options.get.return_value = routing.TeamScheduleOptions(
            has_current_assignment=True, templates=[], patterns=[],
        )
        self.assertEqual(
            await self.request("GET", f"/employee-schedule-assignments/team-options/{self.employee}"), 200,
        )
        self.options.get.assert_awaited_once_with(self.employee)

    async def test_administrator_retains_global_management_and_approval(self):
        self.claims["role"] = "admin"
        self.authorization = CurrentAuthorization(["HR_ADMIN"], ["schedule.manage"], None, None)
        base = "/employee-schedule-assignments"
        self.assertEqual(await self.request("GET", f"{base}/list"), 200)
        self.assertEqual(await self.request("POST", f"{base}/{self.record.id}/approve"), 200)
        self.employees.execute.assert_not_awaited()

    async def test_team_options_filter_other_company_patterns(self):
        company, other_template, pattern_id = uuid4(), uuid4(), uuid4()
        template = ScheduleTemplateEntity(
            id=self.template, company_id=company, schedule_code="DAY", schedule_name="Day",
            schedule_type="FIXED", required_minutes=480, grace_minutes=0, grace_method="NONE",
            is_overnight=False, ot_eligible=True, pre_shift_ot_allowed=False,
            minimum_ot_minutes=0, effective_from=date(2020, 1, 1), effective_to=None,
            status="ACTIVE",
        )
        good = RestDayPatternEntity(
            id=pattern_id, pattern_code="GOOD", pattern_name="Good", cycle_length_days=1,
            description=None, is_active=True,
            days=[RestDayPatternDayEntity(pattern_id=pattern_id, cycle_day_no=1, is_workday=True,
                                          schedule_template_id=self.template)],
        )
        bad_id = uuid4()
        bad = RestDayPatternEntity(
            id=bad_id, pattern_code="OTHER", pattern_name="Other", cycle_length_days=1,
            description=None, is_active=True,
            days=[RestDayPatternDayEntity(pattern_id=bad_id, cycle_day_no=1, is_workday=True,
                                          schedule_template_id=other_template)],
        )
        employment = SimpleNamespace(execute=AsyncMock(return_value=[SimpleNamespace(
            is_active=True, status="ACTIVE", effective_from=date(2020, 1, 1),
            effective_to=None, separation_date=None, company_id=company,
        )]))
        assignments = SimpleNamespace(execute=AsyncMock(return_value=[]))
        templates = SimpleNamespace(execute=AsyncMock(return_value=[template]))
        patterns = SimpleNamespace(execute=AsyncMock(return_value=[good, bad]))
        options = await routing._team_options(self.employee, employment, assignments, templates, patterns)
        self.assertEqual([item.id for item in options.templates], [self.template])
        self.assertEqual([item.id for item in options.patterns], [pattern_id])
        templates.execute.assert_awaited_once_with(company_id=company, limit=1000)
