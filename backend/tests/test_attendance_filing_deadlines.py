import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.attendance.infrastructure import attendance_report_router as reports
from app.attendance.infrastructure import official_business_router as ob
from app.attendance.infrastructure.overtime_repository import SqlAlchemyOvertimeRepository
from app.filemaintenance.leaves.application import leave_records_use_case as leaves
from app.filemaintenance.schedule.application import emergency_schedule_use_cases as emergency
from tests.test_leave_application_submission import SessionUnitOfWork
from tests.test_payroll_cutoff_deadline_policy import make_cutoff


class FilingWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.employee_id = uuid4()
        self.actor_id = uuid4()
        self.cutoff = make_cutoff(
            employee_filing_deadline=self.now - timedelta(days=1),
            attendance_deadline=self.now + timedelta(days=1),
        )
        self.assignment = SimpleNamespace(
            effective_from=date(2026, 10, 1), effective_to=None, separation_date=None,
        )
        self.rows = SimpleNamespace(all=lambda: [(self.cutoff, self.assignment)])
        self.application = SimpleNamespace(
            id=uuid4(), employee_id=self.employee_id, leave_type_id=uuid4(),
            start_at=datetime(2026, 10, 12, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 10, 12, 10, tzinfo=timezone.utc),
            status="DRAFT", is_active=True, updated_by=None, row_version=1,
        )

    def leave_session(self):
        application_result = SimpleNamespace(scalar_one_or_none=lambda: self.application)
        return SimpleNamespace(
            execute=AsyncMock(side_effect=[application_result, self.rows, self.rows]),
            flush=AsyncMock(), refresh=AsyncMock(),
        )

    async def test_leave_creation_rejected_after_filing_before_any_write(self):
        session = SimpleNamespace(execute=AsyncMock(return_value=self.rows), add=Mock(), flush=AsyncMock())
        use_case = leaves.LeaveApplicationUseCase(SessionUnitOfWork(session))
        with patch.object(leaves, "_validate_leave_type_company", new=AsyncMock()):
            with self.assertRaisesRegex(ValueError, "employee filing deadline"):
                await use_case.create({
                    "employee_id": self.employee_id, "leave_type_id": self.application.leave_type_id,
                    "start_at": self.application.start_at, "end_at": self.application.end_at,
                    "status": "PENDING",
                })
        session.add.assert_not_called()
        session.flush.assert_not_awaited()

    async def test_leave_submission_and_edit_rejected_after_filing(self):
        for action in ("submit", "edit"):
            with self.subTest(action=action):
                session = self.leave_session()
                use_case = leaves.LeaveApplicationUseCase(SessionUnitOfWork(session))
                with self.assertRaisesRegex(ValueError, "employee filing deadline"):
                    if action == "submit":
                        await use_case.submit_draft_for_approval(self.application.id, self.actor_id)
                    else:
                        await use_case.update_with_approval_posting(
                            self.application.id, {"remarks": "Changed"}, self.actor_id,
                        )
                session.flush.assert_not_awaited()
                self.assertEqual(self.application.status, "DRAFT")

    async def test_leave_decision_allowed_between_deadlines_but_not_after_approval(self):
        self.application.status = "PENDING"
        session = self.leave_session()
        use_case = leaves.LeaveApplicationUseCase(SessionUnitOfWork(session))
        with patch.object(leaves, "_validate_leave_type_company", new=AsyncMock()), patch.object(
            leaves, "_post_approved_leave_charge", new=AsyncMock(),
        ) as post, patch.object(leaves, "_to_entity", side_effect=lambda model, _: model):
            result = await use_case.update_with_approval_posting(
                self.application.id, {"status": "APPROVED"}, self.actor_id,
            )
        self.assertEqual(result.status, "APPROVED")
        post.assert_awaited_once()
        self.cutoff.attendance_deadline = self.now - timedelta(seconds=1)
        self.application.status = "PENDING"
        session = self.leave_session()
        with self.assertRaisesRegex(ValueError, "attendance deadline"):
            await leaves.LeaveApplicationUseCase(SessionUnitOfWork(session)).update_with_approval_posting(
                self.application.id, {"status": "REJECTED"}, self.actor_id,
            )
        session.flush.assert_not_awaited()

    async def test_leave_midnight_end_does_not_include_next_day(self):
        session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
        with patch.object(leaves, "require_attendance_open", new=AsyncMock()) as guard:
            await leaves._require_leave_open(
                session, self.employee_id,
                datetime(2026, 10, 12, 1, tzinfo=timezone.utc),
                datetime(2026, 10, 12, 16, tzinfo=timezone.utc),
                stage="FILING",
            )
        self.assertEqual(guard.await_args.args[2:4], (date(2026, 10, 12), date(2026, 10, 12)))
        self.assertEqual(guard.await_args.kwargs["stage"], "FILING")

    async def test_leave_date_create_update_and_delete_cannot_bypass_filing(self):
        detail = SimpleNamespace(
            leave_application_id=self.application.id, leave_date=date(2026, 10, 12),
        )
        for action in ("create", "update", "delete"):
            with self.subTest(action=action):
                session = SimpleNamespace(
                    scalar=AsyncMock(side_effect=(
                        [self.application] if action != "update" else [detail, self.application]
                    )),
                    execute=AsyncMock(side_effect=(
                        [SimpleNamespace(scalar_one_or_none=lambda: detail), self.rows]
                        if action == "delete" else [self.rows]
                    )),
                    add=Mock(), delete=AsyncMock(), flush=AsyncMock(),
                )
                use_case = leaves.LeaveApplicationDateUseCase(SessionUnitOfWork(session))
                with self.assertRaisesRegex(ValueError, "employee filing deadline"):
                    if action == "create":
                        await use_case.create({
                            "leave_application_id": self.application.id, "leave_date": detail.leave_date,
                        })
                    elif action == "update":
                        await use_case.update(uuid4(), {"paid_minutes": 60})
                    else:
                        await use_case.delete(uuid4())
                session.add.assert_not_called()
                session.delete.assert_not_awaited()
                session.flush.assert_not_awaited()

    async def test_ob_draft_and_submission_rejected_before_persisting(self):
        for submit in (False, True):
            with self.subTest(submit=submit):
                session = SimpleNamespace(execute=AsyncMock(return_value=self.rows), add=Mock())
                payload = ob.OfficialBusinessCreateSchema(
                    start_at=self.application.start_at, end_at=self.application.end_at,
                    destination="Client office", purpose="Site visit", submit=submit,
                )
                with patch.object(ob, "_employee_for_user", new=AsyncMock(
                    return_value=SimpleNamespace(id=self.employee_id),
                )), patch.object(ob, "_validate_request", new=AsyncMock()):
                    with self.assertRaises(HTTPException) as raised:
                        await ob.create_official_business_request(
                            payload, claims={"sub": str(self.actor_id)},
                            uow=SessionUnitOfWork(session), es_client=None,
                        )
                self.assertEqual(raised.exception.status_code, 409)
                self.assertIn("employee filing deadline", raised.exception.detail)
                session.add.assert_not_called()

    async def test_emergency_schedule_filing_cannot_bypass_deadline(self):
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=self.employee_id),
            execute=AsyncMock(return_value=self.rows), add=Mock(),
        )
        use_case = emergency.SubmitEmergencyScheduleRequestUseCase(SessionUnitOfWork(session))
        with patch.object(emergency, "_active_employee", new=AsyncMock(
            return_value=SimpleNamespace(id=self.employee_id),
        )):
            with self.assertRaisesRegex(ValueError, "employee filing deadline"):
                await use_case.execute(emergency.SubmitEmergencyScheduleRequestInput(
                    employee_id=self.employee_id, user_id=self.actor_id,
                    schedule_template_id=uuid4(), work_date=date(2026, 10, 12), reason="Schedule change",
                ))
        session.add.assert_not_called()

    async def test_overtime_repository_preserves_filing_and_finalization_metadata(self):
        self.cutoff.attendance_finalized_at = self.now
        session = SimpleNamespace(scalar=AsyncMock(return_value=self.cutoff))
        result = await SqlAlchemyOvertimeRepository(session).get_current_cutoff(
            self.employee_id, date(2026, 10, 12),
        )
        self.assertEqual(result.employee_filing_deadline, self.cutoff.employee_filing_deadline)
        self.assertEqual(result.attendance_finalized_at, self.now)
        self.assertEqual(result.status, self.cutoff.status)


class DeadlineVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_permission_denied_before_database_access(self):
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(permission_codes=set())))
        with self.assertRaises(HTTPException) as raised:
            await reports.list_attendance_workflow_deadlines(
                scope="team", claims={"sub": str(uuid4())},
                authorization_use_case=authorization, uow=None,
            )
        self.assertEqual(raised.exception.status_code, 403)

    async def test_own_and_team_queries_scope_assignments_and_expose_both_deadlines(self):
        for scope, permission, column in (
            ("own", "leave.submit", "employee_id"),
            ("team", "leave.approve_team", "supervisor_employee_id"),
        ):
            with self.subTest(scope=scope):
                cutoff = make_cutoff(employee_filing_deadline=None, attendance_finalized_at=None)
                session = SimpleNamespace(
                    scalar=AsyncMock(return_value=uuid4()),
                    scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [cutoff])),
                )
                authorization = SimpleNamespace(execute=AsyncMock(
                    return_value=SimpleNamespace(permission_codes={permission}),
                ))
                response = await reports.list_attendance_workflow_deadlines(
                    scope=scope, claims={"sub": str(uuid4())},
                    authorization_use_case=authorization, uow=SessionUnitOfWork(session),
                )
                statement = str(session.scalars.await_args.args[0])
                self.assertIn(f"employment_assignments.{column} =", statement)
                self.assertIn("employment_assignments.payroll_group_id", statement)
                self.assertIsNone(response.data[0].employee_filing_deadline)
                self.assertEqual(response.data[0].attendance_deadline, cutoff.attendance_deadline)
                self.assertEqual(response.data[0].status, cutoff.status)

    async def test_unlinked_employee_is_rejected(self):
        session = SimpleNamespace(scalar=AsyncMock(return_value=None), scalars=AsyncMock())
        authorization = SimpleNamespace(execute=AsyncMock(
            return_value=SimpleNamespace(permission_codes={"leave.submit"}),
        ))
        with self.assertRaises(HTTPException) as raised:
            await reports.list_attendance_workflow_deadlines(
                scope="own", claims={"sub": str(uuid4())},
                authorization_use_case=authorization, uow=SessionUnitOfWork(session),
            )
        self.assertEqual(raised.exception.status_code, 403)
        session.scalars.assert_not_awaited()
