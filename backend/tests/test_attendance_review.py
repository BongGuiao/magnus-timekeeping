import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.attendance.application.attendance_review_use_cases import (
    ApproveInvalidAttendanceInput,
    ApproveInvalidAttendanceUseCase,
    ListInvalidAttendanceInput,
    ListInvalidAttendanceUseCase,
    RetryUnresolvedAttendanceRouteUseCase,
)
from app.attendance.application.use_case import assign_invalid_attendance_approver
from app.attendance.domain.entities.attendance_employee import AttendanceEmployee
from app.attendance.domain.entities.attendance_review import (
    ReviewableAttendance,
    ReviewableAttendanceRecord,
    UnresolvedAttendanceRouting,
)
from app.attendance.domain.exceptions import ConflictError, RecordNotFoundError, RuleViolationError
from app.attendance.infrastructure.attendance_review_router import (
    approve_supervisor_invalid_attendance,
    get_supervisor_invalid_attendance,
    router,
)
from app.attendance.infrastructure.dependencies import (
    get_list_unresolved_attendance_routes_use_case,
    get_retry_unresolved_attendance_route_use_case,
)
from app.auth.infrastructure.approval_routing import ApprovalRoutingError
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.filemaintenance.payroll_cutoffs.application.deadline_policy import CutoffDeadlineError

# 2026-10-12 17:00 UTC is already 2026-10-13 in Manila.
NOW = datetime(2026, 10, 12, 17, tzinfo=timezone.utc)


def make_record(**changes) -> ReviewableAttendanceRecord:
    values = dict(
        id=uuid4(), user_id=uuid4(), work_date=date(2026, 10, 12), record_status="INVALID",
        clock_in_at=datetime(2026, 10, 12, 1, tzinfo=timezone.utc),
        clock_out_at=datetime(2026, 10, 12, 10, tzinfo=timezone.utc),
        corrected_clock_in_at=datetime(2026, 10, 12, 2, tzinfo=timezone.utc),
    )
    values.update(changes)
    employee = AttendanceEmployee(
        id=uuid4(), employee_no="E-1", first_name="Ana", last_name="Cruz", middle_name="B", preferred_name=" ",
    )
    return ReviewableAttendanceRecord(ReviewableAttendance(**values), employee)


class FakeReviewRepository:
    def __init__(self, record=None):
        self.record = record
        self.calls = []
        self.saved = None
        self.closed_error = None

    async def list_invalid(self, supervisor_employee_id, today, actor_employee_id=None):
        self.calls.append(("list", supervisor_employee_id, today, actor_employee_id))
        return [self.record] if self.record else []

    async def lock_invalid(self, attendance_id, supervisor_employee_id, today, actor_employee_id=None):
        self.calls.append(("lock", attendance_id, supervisor_employee_id, today, actor_employee_id))
        return self.record

    async def save_review(self, attendance):
        self.saved = attendance

    async def require_attendance_open(self, employee_id, work_date, now):
        self.calls.append(("require_open", employee_id, work_date))
        if self.closed_error is not None:
            raise self.closed_error


class FakeUnitOfWork:
    def __init__(self, repository):
        self.review = repository
        self.exit_exception = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.exit_exception = exc_type


class ReviewableAttendanceTests(unittest.TestCase):
    def test_effective_punches_prefer_corrections(self):
        attendance = make_record().attendance
        self.assertEqual(attendance.effective_clock_in, attendance.corrected_clock_in_at)
        self.assertEqual(attendance.effective_clock_out, attendance.clock_out_at)

    def test_approving_marks_valid_with_approver_and_time(self):
        attendance = make_record().attendance
        approver = uuid4()
        attendance.approve(approver, NOW)
        self.assertEqual(
            (attendance.record_status, attendance.approved_by_id, attendance.approved_at),
            ("VALID", approver, NOW),
        )

    def test_only_invalid_attendance_can_be_approved(self):
        with self.assertRaises(RuleViolationError):
            make_record(record_status="VALID").attendance.approve(uuid4(), NOW)

    def test_display_name_skips_blank_preferred_name_and_missing_parts(self):
        self.assertEqual(make_record().employee.display_name, "Ana B Cruz")


class ListInvalidAttendanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_scope_and_philippine_date_are_passed_to_the_repository(self):
        repository = FakeReviewRepository(make_record())
        use_case = ListInvalidAttendanceUseCase(FakeUnitOfWork(repository), clock=lambda: NOW)
        supervisor = uuid4()

        records = await use_case.execute(ListInvalidAttendanceInput(supervisor_employee_id=supervisor))

        self.assertEqual(len(records), 1)
        self.assertEqual(repository.calls, [("list", supervisor, date(2026, 10, 13), None)])


class ApproveInvalidAttendanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.record = make_record()
        self.repository = FakeReviewRepository(self.record)
        self.uow = FakeUnitOfWork(self.repository)
        self.refresher = MagicMock()
        self.audit = MagicMock(record=AsyncMock())
        self.use_case = ApproveInvalidAttendanceUseCase(
            self.uow, self.refresher, self.audit, clock=lambda: NOW,
        )
        self.actor_id = uuid4()

    async def approve(self, supervisor_employee_id=None):
        return await self.use_case.execute(ApproveInvalidAttendanceInput(
            attendance_id=self.record.attendance.id, actor_id=self.actor_id,
            supervisor_employee_id=supervisor_employee_id,
        ))

    async def test_approval_persists_refreshes_the_employee_snapshot_and_audits(self):
        supervisor = uuid4()
        result = await self.approve(supervisor)

        self.assertIs(self.repository.saved, self.record.attendance)
        self.assertEqual(result.attendance.record_status, "VALID")
        self.assertEqual(self.repository.calls[0][2:], (supervisor, date(2026, 10, 13), None))
        self.refresher.request_refresh.assert_called_once_with(self.record.attendance.user_id)
        kwargs = self.audit.record.await_args.kwargs
        self.assertEqual((kwargs["action"], kwargs["resource"]), ("APPROVE", "attendance"))
        self.assertEqual(kwargs["after"], {"record_status": "VALID", "approved_at": NOW.isoformat()})

    async def test_unknown_or_already_reviewed_attendance_is_not_found(self):
        self.repository.record = None
        with self.assertRaises(RecordNotFoundError):
            await self.approve()
        self.assertIsNone(self.repository.saved)
        self.refresher.request_refresh.assert_not_called()
        self.audit.record.assert_not_awaited()
        self.assertIs(self.uow.exit_exception, RecordNotFoundError)

    async def test_attendance_in_closed_cutoff_cannot_be_approved(self):
        self.repository.closed_error = CutoffDeadlineError("deadline passed")
        with self.assertRaisesRegex(ConflictError, "deadline passed"):
            await self.approve()
        self.assertIsNone(self.repository.saved)
        self.assertEqual(self.record.attendance.record_status, "INVALID")
        self.audit.record.assert_not_awaited()


class ReviewRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_response_uses_effective_punches_and_display_name(self):
        record = make_record()
        use_case = MagicMock(execute=AsyncMock(return_value=[record]))
        response = await get_supervisor_invalid_attendance(
            claims={"role": "admin"}, use_case=use_case,
        )
        item = response.data[0]
        self.assertEqual(item.employee_name, "Ana B Cruz")
        self.assertEqual(item.time_in, record.attendance.corrected_clock_in_at)
        self.assertIsNone(use_case.execute.await_args.args[0].supervisor_employee_id)

    async def test_non_admin_without_employee_profile_is_forbidden(self):
        use_case = MagicMock(execute=AsyncMock())
        with self.assertRaises(HTTPException) as error:
            await get_supervisor_invalid_attendance(claims={"role": "user"}, use_case=use_case)
        self.assertEqual(error.exception.status_code, 403)
        use_case.execute.assert_not_awaited()


class InvalidAttendanceRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_approver_is_saved_as_unresolved_without_blocking_punch(self):
        attendance_id, employee_id, actor_id = uuid4(), uuid4(), uuid4()
        with patch(
            "app.attendance.application.use_case.assign_org_approval",
            new=AsyncMock(side_effect=ApprovalRoutingError("No manager configured.")),
        ), patch(
            "app.attendance.application.use_case.save_approval_route", new=AsyncMock()
        ) as save, self.assertLogs("app.attendance.application.use_case", level="WARNING"):
            await assign_invalid_attendance_approver(
                MagicMock(), attendance_id, employee_id, actor_id, NOW.date()
            )
        self.assertEqual(save.await_args.kwargs["resource_id"], attendance_id)
        self.assertEqual(save.await_args.kwargs["routing_error"], "No manager configured.")
        self.assertIsNone(save.await_args.kwargs["approver"])

    async def test_storage_errors_are_not_silently_treated_as_missing_configuration(self):
        with patch(
            "app.attendance.application.use_case.assign_org_approval",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                await assign_invalid_attendance_approver(
                    MagicMock(), uuid4(), uuid4(), uuid4(), NOW.date()
                )

    async def test_retry_commits_updated_error_before_reporting_failure(self):
        repository = FakeReviewRepository()
        repository.retry_unresolved_route = AsyncMock(return_value="Manager still lacks permission.")
        uow = FakeUnitOfWork(repository)
        use_case = RetryUnresolvedAttendanceRouteUseCase(uow, clock=lambda: NOW)
        with self.assertRaisesRegex(ConflictError, "still lacks permission"):
            await use_case.execute(uuid4(), uuid4())
        self.assertIsNone(uow.exit_exception)

    async def test_supervisor_scope_comes_from_the_employee_claim(self):
        employee_id = uuid4()
        use_case = MagicMock(execute=AsyncMock(return_value=[]))
        await get_supervisor_invalid_attendance(
            claims={"role": "user", "employee_id": str(employee_id)}, use_case=use_case,
        )
        self.assertEqual(use_case.execute.await_args.args[0].supervisor_employee_id, employee_id)

    async def test_admin_with_supervisor_role_is_team_scoped(self):
        employee_id = uuid4()
        use_case = MagicMock(execute=AsyncMock(return_value=[]))
        await get_supervisor_invalid_attendance(
            claims={
                "role": "admin",
                "role_codes": ["HR_ADMIN", "SUPERVISOR"],
                "employee_id": str(employee_id),
            },
            use_case=use_case,
        )
        self.assertEqual(use_case.execute.await_args.args[0].supervisor_employee_id, employee_id)

    async def test_approve_translates_not_found_to_404(self):
        use_case = MagicMock(execute=AsyncMock(side_effect=RecordNotFoundError("gone")))
        with self.assertRaises(HTTPException) as error:
            await approve_supervisor_invalid_attendance(
                uuid4(), claims={"sub": str(uuid4()), "role": "admin"}, use_case=use_case,
            )
        self.assertEqual((error.exception.status_code, error.exception.detail), (404, "gone"))

    async def test_approve_requires_actor_and_employee_claims_for_non_admins(self):
        use_case = MagicMock(execute=AsyncMock())
        with self.assertRaises(HTTPException) as error:
            await approve_supervisor_invalid_attendance(
                uuid4(), claims={"sub": str(uuid4()), "role": "user"}, use_case=use_case,
            )
        self.assertEqual(error.exception.status_code, 403)
        use_case.execute.assert_not_awaited()


class UnresolvedAttendanceApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router, prefix="/attendance")
        self.record = make_record()
        self.actor_id = uuid4()
        self.permissions = ["employees.manage"]
        self.list_routes = MagicMock(execute=AsyncMock(return_value=[
            UnresolvedAttendanceRouting(self.record, "No manager configured."),
        ]))
        self.retry_route = MagicMock(execute=AsyncMock())
        self.app.dependency_overrides.update({
            get_current_user_claims: lambda: {"sub": str(self.actor_id)},
            get_current_authorization_use_case: lambda: MagicMock(execute=AsyncMock(
                return_value=MagicMock(permission_codes=self.permissions),
            )),
            get_list_unresolved_attendance_routes_use_case: lambda: self.list_routes,
            get_retry_unresolved_attendance_route_use_case: lambda: self.retry_route,
        })
        self.client = TestClient(self.app)
        self.path = "/attendance/hr/unresolved-attendance-approvals"

    def test_hr_can_list_routes_and_retry(self):
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        item = response.json()["data"][0]
        self.assertEqual(item["id"], str(self.record.attendance.id))
        self.assertEqual(item["routing_error"], "No manager configured.")
        response = self.client.post(f"{self.path}/{self.record.attendance.id}/retry")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"])
        self.retry_route.execute.assert_awaited_once_with(self.record.attendance.id, self.actor_id)

    def test_missing_permission_forbids_list_and_retry(self):
        self.permissions.clear()
        self.assertEqual(self.client.get(self.path).status_code, 403)
        self.assertEqual(self.client.post(f"{self.path}/{self.record.attendance.id}/retry").status_code, 403)
        self.list_routes.execute.assert_not_awaited()
        self.retry_route.execute.assert_not_awaited()

    def test_failed_retry_reports_configuration_error(self):
        self.retry_route.execute.side_effect = ConflictError("Manager still lacks permission.")
        response = self.client.post(f"{self.path}/{self.record.attendance.id}/retry")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Manager still lacks permission.")
