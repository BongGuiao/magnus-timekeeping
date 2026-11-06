import os
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.attendance.application.use_case import assign_invalid_attendance_approver
from app.attendance.infrastructure.admin_dashboard_repository import SqlAlchemyAdminDashboardRepository
from app.attendance.infrastructure.attendance_review_repository import SqlAlchemyAttendanceReviewRepository
from app.attendance.infrastructure import approval_routing_router, attendance_report_router, correction_router, official_business_router
from app.attendance.infrastructure.correction_db_model import AttendanceCorrectionModel
from app.attendance.infrastructure.db_model import AttendanceModel, OfficialBusinessRequestModel, OvertimeApplicationModel
from app.attendance.infrastructure.overtime_repository import SqlAlchemyOvertimeRepository
from app.auth.infrastructure.approval_routing import (
    ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS,
    ApprovalRoutingError,
    approval_route_scope,
    assign_org_approval,
    legacy_supervisor_scope,
    resolve_org_unit_approver,
)
from app.auth.infrastructure.approval_routing_model import ApprovalRouteModel
from app.auth.application.authorization import CurrentAuthorization, GetCurrentAuthorizationUseCase
from app.auth.infrastructure.db_model import RoleModel, UserModel
from app.core.database import init_db_models
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.leaves.application import leave_records_use_case
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import LeaveApplicationModel
from app.filemaintenance.org_unit.infrastructure.db_model import OrgUnit
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_groups.infrastructure.db_model import PayrollGroupModel
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel
from app.filemaintenance.schedule.domain.entities.schedule_upload import NewScheduleUploadBatch, ScheduleUploadBatchRow
from app.filemaintenance.schedule.domain.schedule_upload_exceptions import ScheduleUploadStateError
from app.filemaintenance.schedule.application import emergency_schedule_use_cases
from app.filemaintenance.schedule.infrastructure.db_model import ScheduleTemplateModel
from app.filemaintenance.schedule.infrastructure.emergency_schedule_db_model import EmergencyScheduleRequestModel
from app.filemaintenance.schedule.infrastructure.schedule_upload_db_model import ScheduleUploadBatchModel
from app.filemaintenance.schedule.infrastructure.schedule_upload_repository import SqlAlchemyScheduleUploadRepository

TEST_DATABASE_URL = os.getenv("APPROVAL_ROUTING_TEST_DATABASE_URL")
TODAY = date(2026, 11, 4)
SINCE = date(2020, 1, 1)


class SessionUnitOfWork:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


@unittest.skipUnless(TEST_DATABASE_URL, "Requires a migrated, disposable approval-routing database.")
class OrgUnitApprovalDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if TEST_DATABASE_URL is None:
            self.skipTest("Requires a disposable approval-routing database.")
        if not (make_url(TEST_DATABASE_URL).database or "").startswith("approval_routing_test"):
            raise RuntimeError("Approval-routing tests require an approval_routing_test* database.")
        init_db_models()
        self.engine = create_async_engine(TEST_DATABASE_URL)
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(bind=self.connection, expire_on_commit=False)
        self.addAsyncCleanup(self.cleanup_database)

        self.company_id = await self.session.scalar(select(CompanyModel.id).limit(1))
        self.assertIsNotNone(self.company_id)
        prefix = uuid4().hex[:8]
        self.employees = {
            name: EmployeeModel(
                id=uuid4(), employee_no=f"IT-{prefix}-{name}", first_name=name, last_name="Synthetic",
            )
            for name in ("worker", "manager", "parent", "legacy", "other")
        }
        self.session.add_all(self.employees.values())
        await self.session.flush()
        self.users = {
            name: UserModel(
                id=uuid4(), employee_id=employee.id, username=f"it-{prefix}-{name}",
                password_hash="unused", account_status="ACTIVE",
            )
            for name, employee in self.employees.items()
        }
        self.session.add_all(self.users.values())
        await self.session.flush()
        self.parent = OrgUnit(
            id=uuid4(), company_id=self.company_id, org_unit_code=f"IT-{prefix}-P",
            org_unit_name="Synthetic parent", org_unit_type="DEPARTMENT", effective_from=SINCE,
            manager_employee_id=self.employees["parent"].id,
        )
        self.session.add(self.parent)
        await self.session.flush()
        self.child = OrgUnit(
            id=uuid4(), company_id=self.company_id, parent_org_unit_id=self.parent.id,
            org_unit_code=f"IT-{prefix}-C", org_unit_name="Synthetic child",
            org_unit_type="DEPARTMENT", effective_from=SINCE,
            manager_employee_id=self.employees["manager"].id,
        )
        self.session.add(self.child)
        await self.session.flush()
        self.assignment = EmploymentAssignmentModel(
            employee_id=self.employees["worker"].id, company_id=self.company_id,
            org_unit_id=self.child.id, supervisor_employee_id=self.employees["legacy"].id,
            employment_type="REGULAR", employee_category="REGULAR", hire_date=SINCE, effective_from=SINCE,
        )
        self.session.add(self.assignment)
        for name in ("manager", "parent", "legacy", "other"):
            self.session.add(EmploymentAssignmentModel(
                employee_id=self.employees[name].id, company_id=self.company_id,
                org_unit_id=self.child.id if name == "manager" else self.parent.id,
                employment_type="REGULAR", employee_category="REGULAR", hire_date=SINCE, effective_from=SINCE,
            ))
        roles = {
            role.role_code: role.id
            for role in (await self.session.scalars(
                select(RoleModel).where(RoleModel.role_code.in_(("SUPERVISOR", "MANAGER", "HR_ADMIN")))
            )).all()
        }
        for role_code in ("SUPERVISOR", "MANAGER", "HR_ADMIN"):
            if role_code not in roles:
                role = RoleModel(
                    id=uuid4(), role_code=role_code,
                    role_name=f"Synthetic {role_code}", scope_type="TEAM",
                )
                self.session.add(role)
                roles[role_code] = role.id
        await self.session.flush()
        for name, role_code in (
            ("manager", "SUPERVISOR"), ("parent", "MANAGER"), ("parent", "HR_ADMIN"),
            ("legacy", "SUPERVISOR"), ("other", "MANAGER"),
        ):
            self.session.add(UserRoleModel(user_id=self.users[name].id, role_id=roles[role_code], effective_from=SINCE))
        await self.session.flush()

    async def cleanup_database(self):
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def test_resolver_checks_permissions_and_skips_uploader_and_self(self):
        result = await resolve_org_unit_approver(
            self.session, self.employees["worker"].id, TODAY, "leave.approve_team"
        )
        self.assertEqual(result.employee_id, self.employees["manager"].id)
        parent = await resolve_org_unit_approver(
            self.session, self.employees["worker"].id, TODAY, "schedule.approve",
            excluded_employee_ids=frozenset({self.employees["manager"].id}),
        )
        self.assertEqual(parent.employee_id, self.employees["parent"].id)
        own_request = await resolve_org_unit_approver(
            self.session, self.employees["manager"].id, TODAY, "leave.approve_team"
        )
        self.assertEqual(own_request.employee_id, self.employees["parent"].id)
        schedule_approver = await resolve_org_unit_approver(
            self.session, self.employees["worker"].id, TODAY, "schedule.approve"
        )
        self.assertEqual(schedule_approver.employee_id, self.employees["manager"].id)

    async def test_team_lookup_does_not_require_a_manager_account_for_auto_approval(self):
        self.users["manager"].is_active = False
        await self.session.flush()
        repository = SqlAlchemyScheduleUploadRepository(self.session)
        team = await repository.find_team_employees(
            self.employees["manager"].id, [self.employees["worker"].employee_no], TODAY
        )
        self.assertEqual([employee.employee_id for employee in team], [self.employees["worker"].id])
        with self.assertRaisesRegex(ApprovalRoutingError, "employee-linked account"):
            await resolve_org_unit_approver(
                self.session, self.employees["worker"].id, TODAY, "schedule.approve"
            )

    async def test_authorization_preserves_employee_code_but_rejects_inactive_profile_for_approvals(self):
        use_case = GetCurrentAuthorizationUseCase(SessionUnitOfWork(self.session))
        before = await use_case.execute(self.users["manager"].id)
        self.assertEqual(before.employee_id, self.employees["manager"].id)
        self.assertIn("leave.approve_team", before.permission_codes)
        self.employees["manager"].is_active = False
        await self.session.flush()
        after = await use_case.execute(self.users["manager"].id)
        self.assertIsNone(after.employee_id)
        self.assertEqual(after.employee_code, self.employees["manager"].employee_no)

    async def test_authorization_reads_live_role_assignments(self):
        use_case = GetCurrentAuthorizationUseCase(SessionUnitOfWork(self.session))
        before = await use_case.execute(self.users["legacy"].id)
        self.assertIn("attendance.read_team", before.permission_codes)
        assignment = await self.session.scalar(
            select(UserRoleModel).where(UserRoleModel.user_id == self.users["legacy"].id)
        )
        await self.session.delete(assignment)
        await self.session.flush()
        after = await use_case.execute(self.users["legacy"].id)
        self.assertNotIn("attendance.read_team", after.permission_codes)
        self.assertNotIn("SUPERVISOR", after.role_codes)

    async def test_supervisor_role_alone_does_not_grant_approvals(self):
        use_case = GetCurrentAuthorizationUseCase(SessionUnitOfWork(self.session))
        supervisor = await use_case.execute(self.users["legacy"].id)
        self.assertIn("SUPERVISOR", supervisor.role_codes)
        self.assertFalse((ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS - {"attendance.read_team"}).intersection(supervisor.permission_codes))

    async def test_org_unit_manager_gets_approvals_from_manager_assignment(self):
        use_case = GetCurrentAuthorizationUseCase(SessionUnitOfWork(self.session))
        manager = await use_case.execute(self.users["manager"].id)
        self.assertTrue(ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS.issubset(manager.permission_codes))
        self.assertIn("schedule.approve", manager.permission_codes)
        for permission_code in ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS:
            approver = await resolve_org_unit_approver(
                self.session, self.employees["worker"].id, TODAY, permission_code
            )
            self.assertEqual(approver.employee_id, self.employees["manager"].id)

        self.child.manager_employee_id = None
        await self.session.flush()
        removed = await use_case.execute(self.users["manager"].id)
        self.assertFalse((ORG_UNIT_MANAGER_APPROVAL_PERMISSIONS - {"attendance.read_team"}).intersection(removed.permission_codes))
        with self.assertRaisesRegex(ApprovalRoutingError, "no manager"):
            await resolve_org_unit_approver(
                self.session, self.employees["worker"].id, TODAY, "leave.approve_team"
            )

    async def test_current_org_route_is_stable_and_legacy_follows_supervisor(self):
        requests = []
        for offset in range(2):
            start = datetime(2026, 11, 4 + offset, 1, tzinfo=timezone.utc)
            request = AttendanceCorrectionModel(
                id=uuid4(), employee_id=self.employees["worker"].id, user_id=self.users["worker"].id,
                work_date=start.date(), requested_clock_in_at=start,
                requested_clock_out_at=start + timedelta(hours=8), reason="Synthetic request",
            )
            self.session.add(request)
            requests.append(request)
        await self.session.flush()
        await assign_org_approval(
            self.session, resource_type="attendance_correction", resource_id=requests[0].id,
            employee_id=self.employees["worker"].id, assigned_by=self.users["worker"].id,
            on_date=TODAY, permission_code="leave.approve_team",
        )
        self.session.add(ApprovalRouteModel(
            resource_type="attendance_correction", resource_id=requests[1].id, routing_mode="LEGACY",
        ))
        self.child.manager_employee_id = self.employees["other"].id
        self.assignment.supervisor_employee_id = self.employees["other"].id
        await self.session.flush()

        async def visible_to(employee_id):
            return set((await self.session.scalars(
                select(AttendanceCorrectionModel.id).where(
                    AttendanceCorrectionModel.id.in_([request.id for request in requests]),
                    approval_route_scope(
                        "attendance_correction", AttendanceCorrectionModel.id, employee_id,
                        legacy_supervisor_scope(AttendanceCorrectionModel.employee_id, employee_id, TODAY),
                    ),
                )
            )).all())

        self.assertEqual(await visible_to(self.employees["manager"].id), {requests[0].id})
        self.assertEqual(await visible_to(self.employees["other"].id), {requests[1].id})
        self.assertEqual(await visible_to(self.employees["legacy"].id), set())

    async def test_unresolved_punch_is_listed_for_hr_and_retry_assigns_manager(self):
        record = AttendanceModel(
            id=uuid4(), user_id=self.users["worker"].id, work_date=TODAY, record_status="INVALID",
        )
        self.session.add(record)
        self.child.manager_employee_id = None
        self.parent.manager_employee_id = None
        await self.session.flush()
        with self.assertLogs("app.attendance.application.use_case", level="WARNING"):
            await assign_invalid_attendance_approver(
                self.session, record.id, self.employees["worker"].id, self.users["worker"].id, TODAY
            )
        repository = SqlAlchemyAttendanceReviewRepository(self.session)
        unresolved = await repository.list_unresolved_routes()
        self.assertIn(record.id, {item.record.attendance.id for item in unresolved})
        self.assertIn("no manager", await repository.retry_unresolved_route(
            record.id, self.users["parent"].id, TODAY
        ))
        self.child.manager_employee_id = self.employees["manager"].id
        await self.session.flush()
        self.assertIsNone(await repository.retry_unresolved_route(record.id, self.users["parent"].id, TODAY))
        self.assertNotIn(record.id, {item.record.attendance.id for item in await repository.list_unresolved_routes()})
        visible = await repository.list_invalid(self.employees["manager"].id, TODAY)
        self.assertIn(record.id, {item.attendance.id for item in visible})
        self.assertIsNone(await repository.lock_invalid(record.id, self.employees["other"].id, TODAY))
        self.assertNotIn(record.id, {
            item.attendance.id
            for item in await repository.list_invalid(self.employees["legacy"].id, TODAY)
        })
        self.assertIsNone(await repository.lock_invalid(record.id, self.employees["legacy"].id, TODAY))

    async def test_generic_recovery_preserves_owner_alert_until_configuration_is_fixed(self):
        record = AttendanceModel(
            id=uuid4(), user_id=self.users["worker"].id, work_date=TODAY, record_status="INVALID",
        )
        self.session.add(record)
        self.child.manager_employee_id = None
        await self.session.flush()
        with self.assertLogs("app.attendance.application.use_case", level="WARNING"):
            await assign_invalid_attendance_approver(
                self.session, record.id, self.employees["worker"].id, self.users["worker"].id, TODAY,
            )
        uow = SessionUnitOfWork(self.session)
        authorization = CurrentAuthorization([], [], None, self.employees["worker"].id)

        async def owner_alerts():
            return (await approval_routing_router.list_unresolved_approvals(
                claims={"sub": str(self.users["worker"].id)}, authorization=authorization, uow=uow,
            )).data.records

        alert = next(item for item in await owner_alerts() if item.resource_id == record.id)
        with patch.object(approval_routing_router, "log_entity_action", new=AsyncMock()):
            with self.assertLogs(approval_routing_router.__name__, level="WARNING"):
                failed = await approval_routing_router.recover_unresolved_approval(
                    alert.id, approval_routing_router.RoutingRecoveryInput(),
                    claims={"sub": str(self.users["parent"].id)}, uow=uow, es_client=None,
                )
            self.assertEqual(failed.data.routing_mode, "UNRESOLVED")
            self.assertIn(record.id, {item.resource_id for item in await owner_alerts()})
            self.child.manager_employee_id = self.employees["manager"].id
            await self.session.flush()
            recovered = await approval_routing_router.recover_unresolved_approval(
                alert.id, approval_routing_router.RoutingRecoveryInput(),
                claims={"sub": str(self.users["parent"].id)}, uow=uow, es_client=None,
            )
        self.assertEqual(recovered.data.routing_mode, "ORG_UNIT")
        self.assertNotIn(record.id, {item.resource_id for item in await owner_alerts()})
        self.assertEqual(record.record_status, "INVALID")
        routes = (await self.session.scalars(select(ApprovalRouteModel).where(
            ApprovalRouteModel.resource_type == "invalid_attendance",
            ApprovalRouteModel.resource_id == record.id,
        ))).all()
        self.assertEqual(len(routes), 2)
        current = next(route for route in routes if route.is_current)
        self.assertEqual(current.approver_employee_id, self.employees["manager"].id)

    async def test_manager_request_uses_only_immediate_parent(self):
        approver = await resolve_org_unit_approver(
            self.session, self.employees["manager"].id, TODAY, "leave.approve_team",
        )
        self.assertEqual(approver.employee_id, self.employees["parent"].id)
        self.parent.manager_employee_id = self.employees["manager"].id
        await self.session.flush()
        with self.assertRaisesRegex(ApprovalRoutingError, "parent manager"):
            await resolve_org_unit_approver(
                self.session, self.employees["manager"].id, TODAY, "leave.approve_team",
            )

    async def test_team_deadlines_include_only_authorized_pending_org_routes(self):
        prefix = uuid4().hex[:8]
        group = PayrollGroupModel(
            id=uuid4(), company_id=self.company_id, payroll_group_code=f"IT-{prefix}",
            payroll_group_name="Synthetic group", pay_frequency="SEMIMONTHLY", rate_type="MONTHLY",
        )
        leave_type = LeaveTypeModel(
            id=uuid4(), company_id=self.company_id, leave_code=f"IT-{prefix}",
            leave_name="Synthetic leave", leave_category="OTHER", unit_type="DAYS",
            accrual_method="NONE", effective_from=SINCE,
        )
        template = ScheduleTemplateModel(
            id=uuid4(), company_id=self.company_id, schedule_code=f"IT-{prefix}",
            schedule_name="Synthetic day", schedule_type="FIXED", required_minutes=480,
            effective_from=SINCE, status="ACTIVE",
        )
        self.session.add_all([group, leave_type, template])
        await self.session.flush()
        self.assignment.payroll_group_id = group.id
        cutoff = PayrollCutoffModel(
            id=uuid4(), payroll_group_id=group.id, cutoff_code=f"IT-{prefix}",
            period_start=TODAY - timedelta(days=3), period_end=TODAY + timedelta(days=3),
            pay_date=TODAY + timedelta(days=8),
        )
        start = datetime(2026, 11, 4, 1, tzinfo=timezone.utc)
        attendance = AttendanceModel(
            id=uuid4(), user_id=self.users["worker"].id, work_date=TODAY,
            clock_in_at=start, clock_out_at=start + timedelta(hours=10), record_status="VALID",
        )
        invalid_attendance = AttendanceModel(
            id=uuid4(), user_id=self.users["worker"].id, work_date=TODAY + timedelta(days=1),
            clock_in_at=start + timedelta(days=1), record_status="INVALID",
        )
        self.session.add_all([cutoff, attendance, invalid_attendance])
        await self.session.flush()
        worker_id, worker_user_id = self.employees["worker"].id, self.users["worker"].id
        requests = (
            (
                "leave_application", "leave.approve_team",
                LeaveApplicationModel(
                    id=uuid4(), application_no=f"IT-{prefix}-L", employee_id=worker_id,
                    leave_type_id=leave_type.id, start_at=start, end_at=start + timedelta(hours=8),
                    duration_type="FULL_DAY", requested_minutes=480, reason="Synthetic", status="PENDING",
                ), "status", "REJECTED",
            ),
            (
                "overtime_application", "overtime.approve_team",
                OvertimeApplicationModel(
                    id=uuid4(), application_no=f"IT-{prefix}-O", employee_id=worker_id,
                    attendance_record_id=attendance.id, attendance_date=TODAY,
                    requested_start_at=start + timedelta(hours=9), requested_end_at=start + timedelta(hours=10),
                    potential_ot_minutes=60, requested_minutes=60, overtime_type="REGULAR_OVERTIME",
                    reason="Synthetic", status="PENDING",
                ), "status", "REJECTED",
            ),
            (
                "official_business_request", "official_business.approve_team",
                OfficialBusinessRequestModel(
                    id=uuid4(), request_no=f"IT-{prefix}-OB", employee_id=worker_id,
                    start_at=start, end_at=start + timedelta(hours=2), destination="Synthetic",
                    purpose="Synthetic", requested_minutes=120, status="PENDING",
                ), "status", "REJECTED",
            ),
            (
                "attendance_correction", "attendance.approve_corrections_team",
                AttendanceCorrectionModel(
                    id=uuid4(), employee_id=worker_id, user_id=worker_user_id, work_date=TODAY,
                    requested_clock_in_at=start, requested_clock_out_at=start + timedelta(hours=8),
                    reason="Synthetic", status="PENDING",
                ), "status", "REJECTED",
            ),
            (
                "emergency_schedule_request", "schedule.approve_emergency",
                EmergencyScheduleRequestModel(
                    id=uuid4(), employee_id=worker_id, requested_by=worker_user_id,
                    schedule_template_id=template.id, work_date=TODAY, reason="Synthetic",
                    status="PENDING_APPROVAL",
                ), "status", "REJECTED",
            ),
            ("invalid_attendance", "attendance.read_team", invalid_attendance, "record_status", "VALID"),
        )
        self.session.add_all([item[2] for item in requests[:-1]])
        await self.session.flush()

        async def visible_cutoffs(name, permission):
            authorization = SimpleNamespace(execute=AsyncMock(
                return_value=SimpleNamespace(permission_codes={permission}),
            ))
            response = await attendance_report_router.list_attendance_workflow_deadlines(
                scope="team", claims={"sub": str(self.users[name].id)},
                authorization_use_case=authorization, uow=SessionUnitOfWork(self.session),
            )
            return {item.cutoff_id for item in response.data}

        for resource_type, permission, request, status_field, terminal_status in requests:
            with self.subTest(resource_type=resource_type):
                self.child.manager_employee_id = self.employees["manager"].id
                await self.session.flush()
                await assign_org_approval(
                    self.session, resource_type=resource_type, resource_id=request.id,
                    employee_id=worker_id, assigned_by=worker_user_id, on_date=TODAY,
                    permission_code=permission,
                )
                route = await self.session.scalar(select(ApprovalRouteModel).where(
                    ApprovalRouteModel.resource_type == resource_type,
                    ApprovalRouteModel.resource_id == request.id,
                    ApprovalRouteModel.is_current.is_(True),
                ))
                assert route is not None
                self.child.manager_employee_id = self.employees["other"].id
                await self.session.flush()
                self.assertIn(cutoff.id, await visible_cutoffs("manager", permission))
                self.assertNotIn(cutoff.id, await visible_cutoffs("other", permission))
                self.assertIn(cutoff.id, await visible_cutoffs("legacy", permission))
                different_permission = "leave.approve_team" if permission != "leave.approve_team" else "overtime.approve_team"
                self.assertNotIn(cutoff.id, await visible_cutoffs("manager", different_permission))
                original_status = getattr(request, status_field)
                setattr(request, status_field, terminal_status)
                if resource_type == "emergency_schedule_request":
                    request.reviewed_by = self.users["manager"].id
                    request.reviewed_at = start
                await self.session.flush()
                self.assertNotIn(cutoff.id, await visible_cutoffs("manager", permission))
                setattr(request, status_field, original_status)
                if resource_type == "emergency_schedule_request":
                    request.reviewed_by = None
                    request.reviewed_at = None
                route.is_current = False
                await self.session.flush()

    async def test_team_upload_is_assigned_to_parent_and_keeps_snapshot_after_changes(self):
        repository = SqlAlchemyScheduleUploadRepository(self.session)
        row = ScheduleUploadBatchRow(
            row_no=2, employee_id=self.employees["worker"].id,
            employee_code=self.employees["worker"].employee_no, employee_name="Worker",
            schedule_code="DAY", assignment_type="REGULAR", effective_from=TODAY + timedelta(days=1),
            effective_to=None, rest_day_pattern_code=None, reason=None, company_id=self.company_id,
        )
        team = await repository.find_team_employees(
            self.employees["manager"].id, [row.employee_code], TODAY
        )
        self.assertEqual([employee.employee_id for employee in team], [row.employee_id])
        batch_id = await repository.add_batch(NewScheduleUploadBatch(
            batch_no=f"IT-{uuid4().hex[:16]}", supervisor_employee_id=self.employees["manager"].id,
            uploaded_by=self.users["manager"].id, file_name="test.csv", rows=(row,),
        ))
        await repository.assign_batch_approver(
            batch_id, [row.employee_id], self.users["manager"].id, TODAY
        )
        self.child.manager_employee_id = self.employees["other"].id
        await self.session.flush()
        batch = await repository.get_batch(
            batch_id, reviewer_employee_id=self.employees["parent"].id, review_mode=True, for_update=True,
        )
        self.assertIsNotNone(batch)
        self.assertEqual(batch.approval_routing_mode, "ORG_UNIT")
        self.assertIsNone(await repository.get_batch(
            batch_id, reviewer_employee_id=self.employees["manager"].id, review_mode=True,
        ))
        self.assertIsNone(await repository.get_batch(
            batch_id, reviewer_employee_id=self.employees["legacy"].id,
            supervisor_employee_id=self.employees["legacy"].id, review_mode=True,
        ))
        team_snapshot = await repository.find_team_employees(
            self.employees["manager"].id, [row.employee_code], TODAY,
            scope="SNAPSHOT", snapshot_employee_ids=[row.employee_id],
        )
        self.assertEqual([employee.employee_id for employee in team_snapshot], [row.employee_id])

    async def test_schedule_review_hides_unrouted_pending_but_keeps_scoped_history(self):
        repository = SqlAlchemyScheduleUploadRepository(self.session)
        row = ScheduleUploadBatchRow(
            row_no=2, employee_id=self.employees["worker"].id,
            employee_code=self.employees["worker"].employee_no, employee_name="Worker",
            schedule_code="DAY", assignment_type="REGULAR", effective_from=TODAY + timedelta(days=1),
            effective_to=None, rest_day_pattern_code=None, reason=None, company_id=self.company_id,
        )

        async def make_batch():
            return await repository.add_batch(NewScheduleUploadBatch(
                batch_no=f"IT-{uuid4().hex[:16]}", supervisor_employee_id=self.employees["manager"].id,
                uploaded_by=self.users["manager"].id, file_name="test.csv", rows=(row,),
            ))

        legacy_pending, missing_pending, legacy_history, auto_history = [await make_batch() for _ in range(4)]
        for batch_id in (legacy_pending, legacy_history):
            self.session.add(ApprovalRouteModel(
                resource_type="schedule_upload_batch", resource_id=batch_id, routing_mode="LEGACY",
            ))
        for batch_id in (legacy_history, auto_history):
            batch = await self.session.get(ScheduleUploadBatchModel, batch_id)
            batch.status = "APPROVED"
            batch.reviewed_by = self.users["parent"].id
            batch.reviewed_at = datetime.now(timezone.utc)
        await self.session.flush()

        for batch_id in (legacy_pending, legacy_history, auto_history):
            self.assertIsNotNone(await repository.get_batch(
                batch_id, supervisor_employee_id=self.employees["legacy"].id, review_mode=True,
            ))
        self.assertIsNone(await repository.get_batch(
            missing_pending, supervisor_employee_id=self.employees["legacy"].id, review_mode=True,
        ))
        self.assertIsNone(await repository.get_batch(
            legacy_pending, supervisor_employee_id=self.employees["other"].id, review_mode=True,
        ))
        self.assertIsNone(await repository.get_batch(missing_pending, review_mode=True))
        self.assertIsNotNone(await repository.get_batch(legacy_history, review_mode=True))

    async def test_schedule_upload_rejects_multiple_parent_approvers(self):
        repository = SqlAlchemyScheduleUploadRepository(self.session)
        second_employee = EmployeeModel(
            id=uuid4(), employee_no=f"IT-{uuid4().hex[:8]}-second",
            first_name="Second", last_name="Synthetic",
        )
        self.session.add(second_employee)
        await self.session.flush()
        second_parent = OrgUnit(
            id=uuid4(), company_id=self.company_id, org_unit_code=f"IT-{uuid4().hex[:8]}-P",
            org_unit_name="Second parent", org_unit_type="DEPARTMENT", effective_from=SINCE,
            manager_employee_id=self.employees["other"].id,
        )
        self.session.add(second_parent)
        await self.session.flush()
        second_child = OrgUnit(
            id=uuid4(), company_id=self.company_id, parent_org_unit_id=second_parent.id,
            org_unit_code=f"IT-{uuid4().hex[:8]}-C", org_unit_name="Second child",
            org_unit_type="DEPARTMENT", effective_from=SINCE,
            manager_employee_id=self.employees["manager"].id,
        )
        self.session.add(second_child)
        await self.session.flush()
        self.session.add(EmploymentAssignmentModel(
            employee_id=second_employee.id, company_id=self.company_id, org_unit_id=second_child.id,
            employment_type="REGULAR", employee_category="REGULAR", hire_date=SINCE, effective_from=SINCE,
        ))
        role_id = await self.session.scalar(select(RoleModel.id).where(RoleModel.role_code == "HR_ADMIN"))
        self.session.add(UserRoleModel(
            user_id=self.users["other"].id, role_id=role_id, effective_from=SINCE,
        ))
        await self.session.flush()
        rows = tuple(
            ScheduleUploadBatchRow(
                row_no=index, employee_id=employee.id, employee_code=employee.employee_no,
                employee_name=employee.first_name, schedule_code="DAY", assignment_type="REGULAR",
                effective_from=TODAY + timedelta(days=1), effective_to=None,
                rest_day_pattern_code=None, reason=None, company_id=self.company_id,
            )
            for index, employee in enumerate((self.employees["worker"], second_employee), start=2)
        )
        batch_id = await repository.add_batch(NewScheduleUploadBatch(
            batch_no=f"IT-{uuid4().hex[:16]}", supervisor_employee_id=self.employees["manager"].id,
            uploaded_by=self.users["manager"].id, file_name="test.csv", rows=rows,
        ))
        with self.assertRaisesRegex(ScheduleUploadStateError, "more than one organization approver"):
            await repository.assign_batch_approver(
                batch_id, [row.employee_id for row in rows], self.users["manager"].id, TODAY,
            )
        route = await self.session.scalar(select(ApprovalRouteModel).where(
            ApprovalRouteModel.resource_type == "schedule_upload_batch",
            ApprovalRouteModel.resource_id == batch_id,
            ApprovalRouteModel.is_current.is_(True),
        ))
        self.assertIsNone(route)

    async def test_legacy_requests_cannot_be_self_approved_in_list_or_decision_paths(self):
        manager_id = self.employees["manager"].id
        manager_user_id = self.users["manager"].id
        assignment = await self.session.scalar(select(EmploymentAssignmentModel).where(
            EmploymentAssignmentModel.employee_id == manager_id,
        ))
        assignment.supervisor_employee_id = manager_id
        leave_type = LeaveTypeModel(
            id=uuid4(), company_id=self.company_id, leave_code=f"IT-{uuid4().hex[:8]}",
            leave_name="Synthetic leave", leave_category="OTHER", unit_type="DAYS",
            accrual_method="NONE", effective_from=SINCE,
        )
        self.session.add(leave_type)
        await self.session.flush()
        start = datetime(2026, 11, 4, 1, tzinfo=timezone.utc)
        leave = LeaveApplicationModel(
            id=uuid4(), application_no=f"IT-{uuid4().hex}", employee_id=manager_id,
            leave_type_id=leave_type.id, start_at=start, end_at=start + timedelta(hours=8),
            duration_type="FULL_DAY", requested_minutes=480, reason="Synthetic", status="PENDING",
        )
        attendance = AttendanceModel(
            id=uuid4(), user_id=manager_user_id, work_date=TODAY, record_status="INVALID",
            clock_in_at=start, clock_out_at=start + timedelta(hours=10),
        )
        self.session.add_all([leave, attendance])
        await self.session.flush()
        overtime = OvertimeApplicationModel(
            id=uuid4(), application_no=f"IT-{uuid4().hex}", employee_id=manager_id,
            attendance_record_id=attendance.id, attendance_date=TODAY,
            requested_start_at=start + timedelta(hours=9), requested_end_at=start + timedelta(hours=10),
            potential_ot_minutes=60, requested_minutes=60, overtime_type="REGULAR_OVERTIME",
            reason="Synthetic", status="PENDING",
        )
        self.session.add(overtime)
        repository = SqlAlchemyScheduleUploadRepository(self.session)
        row = ScheduleUploadBatchRow(
            row_no=2, employee_id=manager_id, employee_code=self.employees["manager"].employee_no,
            employee_name="Manager", schedule_code="DAY", assignment_type="REGULAR",
            effective_from=TODAY + timedelta(days=1), effective_to=None, rest_day_pattern_code=None,
            reason=None, company_id=self.company_id,
        )
        batch_id = await repository.add_batch(NewScheduleUploadBatch(
            batch_no=f"IT-{uuid4().hex[:16]}", supervisor_employee_id=manager_id,
            uploaded_by=self.users["parent"].id, file_name="test.csv", rows=(row,),
        ))
        self.session.add_all([
            ApprovalRouteModel(resource_type=resource_type, resource_id=resource_id, routing_mode="LEGACY")
            for resource_type, resource_id in (
                ("leave_application", leave.id), ("invalid_attendance", attendance.id),
                ("overtime_application", overtime.id), ("schedule_upload_batch", batch_id),
            )
        ])
        await self.session.flush()

        leave_use_case = leave_records_use_case.LeaveApplicationUseCase(SessionUnitOfWork(self.session))
        self.assertEqual(await leave_use_case.count_pending_for_supervisor(manager_id, TODAY), 0)
        self.assertEqual(await leave_use_case.list_pending_for_supervisor(manager_id, TODAY), [])
        self.assertIsNone(await leave_use_case.decide_pending_for_supervisor(
            manager_id, leave.id, "REJECTED", manager_user_id, TODAY,
        ))
        self.assertEqual(await SqlAlchemyAdminDashboardRepository(self.session).list_pending_leaves(
            supervisor_employee_id=manager_id, today=TODAY,
        ), [])
        with self.assertRaisesRegex(ValueError, "own leave application"):
            await leave_use_case.update_with_approval_posting(leave.id, {"status": "REJECTED"}, manager_user_id)
        with patch.object(leave_records_use_case, "_validate_leave_type_company", new=AsyncMock()), patch.object(
            leave_records_use_case, "_require_leave_open", new=AsyncMock()
        ):
            result = await leave_use_case.update_with_approval_posting(
                leave.id, {"status": "REJECTED"}, self.users["parent"].id,
            )
        self.assertEqual(result.status, "REJECTED")

        attendance_repository = SqlAlchemyAttendanceReviewRepository(self.session)
        self.assertEqual(await attendance_repository.list_invalid(manager_id, TODAY), [])
        self.assertIsNone(await attendance_repository.lock_invalid(attendance.id, None, TODAY, manager_id))
        overtime_repository = SqlAlchemyOvertimeRepository(self.session)
        self.assertNotIn(overtime.id, {
            item.application.id for item in await overtime_repository.list_pending_applications(None, manager_id)
        })
        self.assertIsNone(await overtime_repository.lock_pending_application(overtime.id, None, manager_id))
        self.assertIsNone(await repository.get_batch(
            batch_id, reviewer_employee_id=manager_id, review_mode=True,
        ))
        batch = await self.session.get(ScheduleUploadBatchModel, batch_id)
        batch.status = "APPROVED"
        batch.reviewed_by = self.users["other"].id
        batch.reviewed_at = datetime.now(timezone.utc)
        await self.session.flush()
        self.assertIsNotNone(await repository.get_batch(
            batch_id, reviewer_employee_id=manager_id, review_mode=True,
        ))

    async def test_leave_submission_inbox_and_decision_use_saved_manager(self):
        leave_type = LeaveTypeModel(
            id=uuid4(), company_id=self.company_id, leave_code=f"IT-{uuid4().hex[:8]}",
            leave_name="Synthetic leave", leave_category="OTHER", unit_type="DAYS",
            accrual_method="NONE", effective_from=SINCE,
        )
        self.session.add(leave_type)
        await self.session.flush()
        start = datetime(2026, 11, 5, 1, tzinfo=timezone.utc)
        use_case = leave_records_use_case.LeaveApplicationUseCase(SessionUnitOfWork(self.session))
        with patch.object(leave_records_use_case, "_validate_leave_type_company", new=AsyncMock()), patch.object(
            leave_records_use_case, "_require_leave_open", new=AsyncMock()
        ):
            draft = await use_case.create({
                "application_no": f"IT-{uuid4().hex}", "employee_id": self.employees["worker"].id,
                "leave_type_id": leave_type.id, "start_at": start, "end_at": start + timedelta(hours=8),
                "duration_type": "FULL_DAY", "requested_minutes": 480, "reason": "Synthetic",
                "status": "DRAFT", "created_by": self.users["worker"].id,
            })
            pending = await use_case.submit_draft_for_approval(draft.id, self.users["worker"].id)
            self.child.manager_employee_id = self.employees["other"].id
            await self.session.flush()
            manager_id = self.employees["manager"].id
            other_id = self.employees["other"].id
            legacy_id = self.employees["legacy"].id
            self.assertEqual(await use_case.count_pending_for_supervisor(manager_id, TODAY), 1)
            self.assertEqual(await use_case.count_pending_for_supervisor(other_id, TODAY), 0)
            self.assertEqual(await use_case.count_pending_for_supervisor(legacy_id, TODAY), 0)
            self.assertEqual([item["id"] for item in await use_case.list_pending_for_supervisor(manager_id, TODAY)],
                             [pending.id])
            self.assertEqual(await use_case.list_pending_for_supervisor(legacy_id, TODAY), [])
            self.assertIsNone(await use_case.decide_pending_for_supervisor(
                other_id, pending.id, "REJECTED", self.users["other"].id, TODAY,
            ))
            self.assertIsNone(await use_case.decide_pending_for_supervisor(
                legacy_id, pending.id, "REJECTED", self.users["legacy"].id, TODAY,
            ))
            decided = await use_case.decide_pending_for_supervisor(
                manager_id, pending.id, "REJECTED", self.users["manager"].id, TODAY,
            )
            self.assertEqual(decided.status, "REJECTED")

    async def test_correction_submission_inbox_and_decision_use_saved_manager(self):
        start = datetime(2026, 11, 4, 1, tzinfo=timezone.utc)
        record = AttendanceModel(
            id=uuid4(), user_id=self.users["worker"].id, work_date=TODAY,
            clock_in_at=start, expected_clock_in_at=start, expected_clock_out_at=start + timedelta(hours=9),
            record_status="VALID", punch_metadata={"schedule_context": {"ot_eligible": True}},
        )
        self.session.add(record)
        await self.session.flush()
        uow = SessionUnitOfWork(self.session)
        worker_claims = {"sub": str(self.users["worker"].id)}
        manager_claims = {"sub": str(self.users["manager"].id)}
        other_claims = {"sub": str(self.users["other"].id)}
        legacy_claims = {"sub": str(self.users["legacy"].id)}
        payload = correction_router.CorrectionCreate(
            work_date=TODAY, requested_clock_in_at=start, requested_clock_out_at=start + timedelta(hours=9),
            reason="Synthetic correction",
        )
        with patch.object(correction_router, "_open", new=AsyncMock(return_value=[])), patch.object(
            correction_router, "log_entity_action", new=AsyncMock()
        ), patch.object(correction_router, "queue_recent_attendance_refresh"):
            created = (await correction_router.create_correction(
                payload, claims=worker_claims, uow=uow, es_client=None,
            )).data
            self.child.manager_employee_id = self.employees["other"].id
            await self.session.flush()
            manager_items = (await correction_router.pending_corrections(claims=manager_claims, uow=uow)).data
            other_items = (await correction_router.pending_corrections(claims=other_claims, uow=uow)).data
            legacy_items = (await correction_router.pending_corrections(claims=legacy_claims, uow=uow)).data
            self.assertIn(created.id, {item.id for item in manager_items})
            self.assertNotIn(created.id, {item.id for item in other_items})
            self.assertNotIn(created.id, {item.id for item in legacy_items})
            decision = correction_router.CorrectionDecision(
                decision="REJECTED", row_version=created.row_version, review_notes="Synthetic review",
            )
            with self.assertRaises(HTTPException) as denied:
                await correction_router.decide_correction(
                    created.id, decision, claims=other_claims, uow=uow, es_client=None,
                )
            self.assertEqual(denied.exception.status_code, 404)
            with self.assertRaises(HTTPException) as legacy_denied:
                await correction_router.decide_correction(
                    created.id, decision, claims=legacy_claims, uow=uow, es_client=None,
                )
            self.assertEqual(legacy_denied.exception.status_code, 404)
            result = await correction_router.decide_correction(
                created.id, decision, claims=manager_claims, uow=uow, es_client=None,
            )
            self.assertEqual(result.data.status, "REJECTED")

    async def test_official_business_submission_inbox_and_decision_use_saved_manager(self):
        start = datetime(2026, 11, 4, 1, tzinfo=timezone.utc)
        uow = SessionUnitOfWork(self.session)

        def claims(name):
            return {
                "sub": str(self.users[name].id), "employee_id": str(self.employees[name].id),
                "role": "user", "role_codes": ["SUPERVISOR"],
            }

        payload = official_business_router.OfficialBusinessCreateSchema(
            start_at=start, end_at=start + timedelta(hours=2), destination="Synthetic",
            purpose="Synthetic visit", submit=True,
        )
        with patch.object(official_business_router, "_validate_request", new=AsyncMock()), patch.object(
            official_business_router, "require_attendance_open", new=AsyncMock()
        ), patch.object(official_business_router, "log_entity_action", new=AsyncMock()):
            created = (await official_business_router.create_official_business_request(
                payload, claims=claims("worker"), uow=uow, es_client=None,
            )).data
            self.child.manager_employee_id = self.employees["other"].id
            await self.session.flush()
            manager_items = (await official_business_router.get_pending_official_business_requests(
                claims=claims("manager"), uow=uow,
            )).data
            other_items = (await official_business_router.get_pending_official_business_requests(
                claims=claims("other"), uow=uow,
            )).data
            legacy_items = (await official_business_router.get_pending_official_business_requests(
                claims=claims("legacy"), uow=uow,
            )).data
            self.assertIn(created.id, {item.id for item in manager_items})
            self.assertNotIn(created.id, {item.id for item in other_items})
            self.assertNotIn(created.id, {item.id for item in legacy_items})
            decision = official_business_router.OfficialBusinessDecisionSchema(
                decision="REJECTED", row_version=created.row_version,
            )
            with self.assertRaises(HTTPException) as denied:
                await official_business_router.decide_official_business_request(
                    created.id, decision, claims=claims("other"), uow=uow, es_client=None,
                )
            self.assertEqual(denied.exception.status_code, 404)
            with self.assertRaises(HTTPException) as legacy_denied:
                await official_business_router.decide_official_business_request(
                    created.id, decision, claims=claims("legacy"), uow=uow, es_client=None,
                )
            self.assertEqual(legacy_denied.exception.status_code, 404)
            result = await official_business_router.decide_official_business_request(
                created.id, decision, claims=claims("manager"), uow=uow, es_client=None,
            )
            self.assertEqual(result.data.status, "REJECTED")

    async def test_overtime_inbox_and_decision_lookup_use_saved_manager(self):
        start = datetime(2026, 11, 4, 1, tzinfo=timezone.utc)
        attendance = AttendanceModel(
            id=uuid4(), user_id=self.users["worker"].id, work_date=TODAY,
            clock_in_at=start, clock_out_at=start + timedelta(hours=10), record_status="VALID",
        )
        self.session.add(attendance)
        await self.session.flush()
        application = OvertimeApplicationModel(
            id=uuid4(), application_no=f"IT-{uuid4().hex}", employee_id=self.employees["worker"].id,
            attendance_record_id=attendance.id, attendance_date=TODAY,
            requested_start_at=start + timedelta(hours=9), requested_end_at=start + timedelta(hours=10),
            potential_ot_minutes=60, requested_minutes=60, overtime_type="REGULAR_OVERTIME",
            reason="Synthetic overtime", status="PENDING",
        )
        self.session.add(application)
        await self.session.flush()
        repository = SqlAlchemyOvertimeRepository(self.session)
        await repository.assign_approver(
            application.id, self.employees["worker"].id, self.users["worker"].id, TODAY,
        )
        self.child.manager_employee_id = self.employees["other"].id
        await self.session.flush()
        manager_id, other_id = self.employees["manager"].id, self.employees["other"].id
        legacy_id = self.employees["legacy"].id
        self.assertIn(application.id, {
            item.application.id for item in await repository.list_pending_applications(manager_id)
        })
        self.assertNotIn(application.id, {
            item.application.id for item in await repository.list_pending_applications(other_id)
        })
        self.assertNotIn(application.id, {
            item.application.id for item in await repository.list_pending_applications(legacy_id)
        })
        self.assertIsNone(await repository.lock_pending_application(application.id, other_id))
        self.assertIsNone(await repository.lock_pending_application(application.id, legacy_id))
        self.assertIsNotNone(await repository.lock_pending_application(application.id, manager_id))

    async def test_emergency_submission_inbox_and_decision_use_saved_manager(self):
        template = ScheduleTemplateModel(
            id=uuid4(), company_id=self.company_id, schedule_code=f"IT-{uuid4().hex[:8]}",
            schedule_name="Synthetic day", schedule_type="FIXED", required_minutes=480,
            effective_from=SINCE, status="ACTIVE",
        )
        self.session.add(template)
        await self.session.flush()
        uow = SessionUnitOfWork(self.session)
        with patch.object(emergency_schedule_use_cases, "require_attendance_open", new=AsyncMock()), patch.object(
            emergency_schedule_use_cases, "_validate_retroactive_work_date", new=AsyncMock(return_value=False)
        ):
            created = await emergency_schedule_use_cases.SubmitEmergencyScheduleRequestUseCase(uow).execute(
                emergency_schedule_use_cases.SubmitEmergencyScheduleRequestInput(
                    employee_id=self.employees["worker"].id, user_id=self.users["worker"].id,
                    schedule_template_id=template.id, work_date=TODAY + timedelta(days=1), reason="Synthetic",
                )
            )
            self.child.manager_employee_id = self.employees["other"].id
            await self.session.flush()
            pending = emergency_schedule_use_cases.ListPendingEmergencyScheduleRequestsUseCase(uow)
            manager_items = await pending.execute(
                emergency_schedule_use_cases.ListPendingEmergencyScheduleRequestsInput(self.employees["manager"].id)
            )
            other_items = await pending.execute(
                emergency_schedule_use_cases.ListPendingEmergencyScheduleRequestsInput(self.employees["other"].id)
            )
            legacy_items = await pending.execute(
                emergency_schedule_use_cases.ListPendingEmergencyScheduleRequestsInput(self.employees["legacy"].id)
            )
            self.assertIn(created.id, {item.id for item in manager_items})
            self.assertNotIn(created.id, {item.id for item in other_items})
            self.assertNotIn(created.id, {item.id for item in legacy_items})
            review = emergency_schedule_use_cases.ReviewEmergencyScheduleRequestUseCase(uow)
            with self.assertRaisesRegex(ValueError, "assigned approver"):
                await review.execute(emergency_schedule_use_cases.ReviewEmergencyScheduleRequestInput(
                    request_id=created.id, supervisor_employee_id=self.employees["other"].id,
                    reviewer_user_id=self.users["other"].id, decision="REJECTED", remarks="Synthetic review",
                ))
            with self.assertRaisesRegex(ValueError, "assigned approver"):
                await review.execute(emergency_schedule_use_cases.ReviewEmergencyScheduleRequestInput(
                    request_id=created.id, supervisor_employee_id=self.employees["legacy"].id,
                    reviewer_user_id=self.users["legacy"].id, decision="REJECTED", remarks="Synthetic review",
                ))
            result = await review.execute(emergency_schedule_use_cases.ReviewEmergencyScheduleRequestInput(
                request_id=created.id, supervisor_employee_id=self.employees["manager"].id,
                reviewer_user_id=self.users["manager"].id, decision="REJECTED", remarks="Synthetic review",
            ))
            self.assertEqual(result.status, "REJECTED")


if __name__ == "__main__":
    unittest.main()
