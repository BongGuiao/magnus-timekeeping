import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.filemaintenance.leaves.application import leave_records_use_case as leave
from app.filemaintenance.leaves.application.leave_duration import LeaveDuration, LeaveDurationDay
from app.filemaintenance.leaves.infrastructure.leave_records_router import require_hr_leave_reversal_access


class UnitOfWork:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def fixture():
    tz = ZoneInfo("Asia/Manila")
    application = SimpleNamespace(
        id=uuid4(), employee_id=uuid4(), leave_type_id=uuid4(), application_no="LV-1",
        start_at=datetime(2026, 12, 16, 0, tzinfo=tz), end_at=datetime(2026, 12, 16, 5, tzinfo=tz),
        status="APPROVED", is_active=True, payroll_posted=False, paid_minutes=300, unpaid_minutes=0,
        approved_at=datetime(2026, 11, 20, tzinfo=tz), row_version=1,
    )
    day = SimpleNamespace(
        leave_date=date(2026, 12, 15), requested_minutes=300,
        approved_paid_minutes=300, approved_unpaid_minutes=0, final_charge_minutes=300,
    )
    entitlement = SimpleNamespace(
        opening_minutes=600, granted_minutes=0, accrued_minutes=0, carryover_minutes=0,
        adjustment_minutes=0, used_minutes=300, reserved_minutes=0, expired_minutes=0,
        converted_minutes=0, available_minutes=300, last_calculated_at=None,
    )
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[
            SimpleNamespace(scalar_one_or_none=lambda: application),
            SimpleNamespace(scalar_one=lambda: -300),
            SimpleNamespace(scalar_one_or_none=lambda: entitlement),
        ]),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [day])),
        add=unittest.mock.Mock(), flush=AsyncMock(), refresh=AsyncMock(),
    )
    return application, day, entitlement, session


class LeaveApprovalReversalTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_active_hr_admin_in_hr_dashboard_can_access(self):
        claims = {"sub": str(uuid4()), "email": "hr@example.invalid"}
        employee_id = uuid4()
        auth = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            role_codes=["HR_ADMIN"], employee_id=employee_id,
        )))
        self.assertEqual(await require_hr_leave_reversal_access("HR_ADMIN", claims, auth), (UUID(claims["sub"]), employee_id))
        for role_codes, mode, profile in [
            (["SYSTEM_ADMIN"], "HR_ADMIN", employee_id),
            (["HR_ADMIN"], "EMPLOYEE", employee_id),
            (["HR_ADMIN"], "HR_ADMIN", None),
        ]:
            auth.execute.return_value = SimpleNamespace(role_codes=role_codes, employee_id=profile)
            with self.assertRaises(HTTPException) as error:
                await require_hr_leave_reversal_access(mode, claims, auth)
            self.assertEqual(error.exception.status_code, 403)

    async def test_reversal_restores_balance_and_reroutes_with_durable_reason(self):
        application, day, entitlement, session = fixture()
        actor_id, actor_employee_id = uuid4(), uuid4()
        with patch.object(leave, "require_attendance_open", new=AsyncMock()) as deadline, \
                patch.object(leave, "assign_org_approval", new=AsyncMock()) as route, \
                patch.object(leave, "_to_entity", side_effect=lambda model, _: model):
            result = await leave.LeaveApplicationUseCase(UnitOfWork(session)).return_approved_to_pending(
                application.id, actor_id, actor_employee_id, "Wrong dates",
            )
        self.assertEqual(result.status, "PENDING")
        self.assertIsNone(result.approved_at)
        self.assertEqual((entitlement.used_minutes, entitlement.available_minutes), (0, 600))
        self.assertEqual((day.approved_paid_minutes, day.approved_unpaid_minutes, day.final_charge_minutes), (0, 0, 0))
        record = session.add.call_args.args[0]
        self.assertEqual((record.transaction_type, record.minutes_delta, record.posted_by), ("LEAVE_REVERSAL", 300, actor_id))
        self.assertIn("Wrong dates", record.remarks)
        self.assertEqual(deadline.await_args.args[2:4], (date(2026, 12, 15), date(2026, 12, 16)))
        self.assertTrue(deadline.await_args.kwargs["lock_for_update"])
        self.assertEqual(route.await_args.kwargs["employee_id"], application.employee_id)
        self.assertNotIn("hold_unresolved", route.await_args.kwargs)
        session.execute.side_effect = [SimpleNamespace(scalar_one_or_none=lambda: application)]
        with self.assertRaisesRegex(ValueError, "Only approved"):
            await leave.LeaveApplicationUseCase(UnitOfWork(session)).return_approved_to_pending(
                application.id, actor_id, actor_employee_id, "Again",
            )
        self.assertEqual(session.add.call_count, 1)

    async def test_reversal_refuses_own_leave_closed_cutoffs_and_inconsistent_ledger(self):
        application, day, entitlement, session = fixture()
        use_case = leave.LeaveApplicationUseCase(UnitOfWork(session))
        with self.assertRaisesRegex(ValueError, "own leave"):
            await use_case.return_approved_to_pending(application.id, uuid4(), application.employee_id, "Reason")
        self.assertEqual(entitlement.used_minutes, 300)
        application, day, entitlement, session = fixture()
        with patch.object(leave, "require_attendance_open", new=AsyncMock(side_effect=ValueError("cutoff closed"))):
            with self.assertRaisesRegex(ValueError, "cutoff closed"):
                await leave.LeaveApplicationUseCase(UnitOfWork(session)).return_approved_to_pending(
                    application.id, uuid4(), uuid4(), "Reason",
                )
        self.assertEqual(application.status, "APPROVED")
        self.assertEqual(entitlement.used_minutes, 300)
        session.add.assert_not_called()
        application, day, entitlement, session = fixture()
        session.execute.side_effect = [
            SimpleNamespace(scalar_one_or_none=lambda: application),
            SimpleNamespace(scalar_one=lambda: 0),
        ]
        with patch.object(leave, "require_attendance_open", new=AsyncMock()):
            with self.assertRaisesRegex(ValueError, "ledger do not match"):
                await leave.LeaveApplicationUseCase(UnitOfWork(session)).return_approved_to_pending(
                    application.id, uuid4(), uuid4(), "Reason",
                )
        self.assertEqual(application.status, "APPROVED")
        session.add.assert_not_called()

    async def test_reversal_refuses_payroll_posting_and_unresolved_routing(self):
        application, _, entitlement, session = fixture()
        application.payroll_posted = True
        with self.assertRaisesRegex(ValueError, "Payroll-posted"):
            await leave.LeaveApplicationUseCase(UnitOfWork(session)).return_approved_to_pending(
                application.id, uuid4(), uuid4(), "Correction",
            )
        self.assertEqual(entitlement.used_minutes, 300)
        application, _, entitlement, session = fixture()
        with patch.object(leave, "require_attendance_open", new=AsyncMock()), \
                patch.object(leave, "assign_org_approval", new=AsyncMock(side_effect=ValueError("No current approver"))):
            with self.assertRaisesRegex(ValueError, "No current approver"):
                await leave.LeaveApplicationUseCase(UnitOfWork(session)).return_approved_to_pending(
                    application.id, uuid4(), uuid4(), "Correction",
                )
        self.assertEqual(application.status, "APPROVED")
        self.assertEqual(entitlement.used_minutes, 300)
        session.add.assert_not_called()

    async def test_reapproval_rejects_an_outstanding_charge(self):
        application, _, _, session = fixture()
        session.execute.side_effect = [SimpleNamespace(scalar_one_or_none=lambda: -300)]
        with self.assertRaisesRegex(ValueError, "outstanding leave charge"):
            await leave._post_approved_leave_charge(session, application, uuid4())

    async def test_return_then_reapproval_charges_once_again(self):
        application, day, entitlement, session = fixture()
        application.requested_minutes = 300
        use_case = leave.LeaveApplicationUseCase(UnitOfWork(session))
        with patch.object(leave, "require_attendance_open", new=AsyncMock()), \
                patch.object(leave, "assign_org_approval", new=AsyncMock()), \
                patch.object(leave, "_to_entity", side_effect=lambda model, _: model):
            await use_case.return_approved_to_pending(application.id, uuid4(), uuid4(), "Correction")
        session.execute.side_effect = [
            SimpleNamespace(scalar_one_or_none=lambda: 0),
            SimpleNamespace(scalar_one_or_none=lambda: entitlement),
        ]
        duration = LeaveDuration((LeaveDurationDay(day.leave_date, 300),), (), ())
        with patch.object(leave, "_validated_duration", new=AsyncMock(return_value=duration)), \
                patch.object(leave, "_require_duration_open", new=AsyncMock()):
            await leave._post_approved_leave_charge(session, application, uuid4())
        self.assertEqual((entitlement.used_minutes, entitlement.available_minutes), (300, 300))
        self.assertEqual((day.approved_paid_minutes, application.paid_minutes), (300, 300))
        records = [call.args[0] for call in session.add.call_args_list]
        self.assertEqual([(row.transaction_type, row.minutes_delta) for row in records], [
            ("LEAVE_REVERSAL", 300), ("LEAVE_USED", -300),
        ])
