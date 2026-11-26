import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import create_engine, text

from app.filemaintenance.leaves.application import leave_records_use_case as leave
from app.filemaintenance.leaves.application.leave_duration import LeaveDuration, LeaveDurationDay
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import LeaveApplicationModel
from app.filemaintenance.leaves.infrastructure.leave_records_router import (
    LeaveReversalRequest, list_approved_leave_for_reversal, return_approved_leave_for_approval,
)
from app.auth.infrastructure.hr_dashboard_access import (
    ApprovalReturnActor, require_hr_dashboard_access, require_approval_return_access,
)


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
        approved_at=datetime(2026, 11, 20, tzinfo=tz), approved_by_id=uuid4(), row_version=1,
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
    async def test_approved_leave_is_sorted_before_pagination(self):
        engine = create_engine("sqlite://")
        connection = engine.connect()
        try:
            connection.execute(text("ATTACH DATABASE ':memory:' AS leave_mgmt"))
            connection.execute(text("ATTACH DATABASE ':memory:' AS hr"))
            connection.execute(text(
                "CREATE TABLE hr.employees (id CHAR(32), first_name TEXT, last_name TEXT)"
            ))
            connection.execute(text(
                "CREATE TABLE leave_mgmt.leave_types (id CHAR(32), leave_name TEXT)"
            ))
            connection.execute(text(
                "CREATE TABLE leave_mgmt.leave_applications (id CHAR(32), employee_id CHAR(32), leave_type_id CHAR(32),"
                " application_no TEXT, status TEXT, is_active BOOLEAN, start_at DATETIME, end_at DATETIME, paid_minutes INTEGER, approved_by_id CHAR(32))"
            ))
            leave_type_id = uuid4()
            connection.execute(text("INSERT INTO leave_mgmt.leave_types VALUES (:id, 'Vacation')"), {"id": leave_type_id.hex})
            records = {}
            approver_id = uuid4()
            for index in range(30):
                app_id, employee_id = uuid4(), uuid4()
                name = f"Employee {29 - index:02}"
                connection.execute(text("INSERT INTO hr.employees VALUES (:id, :name, 'Test')"), {
                    "id": employee_id.hex, "name": name,
                })
                connection.execute(text(
                    "INSERT INTO leave_mgmt.leave_applications VALUES "
                    "(:id, :employee, :leave_type, :number, 'APPROVED', 1,"
                    " '2026-12-10 09:00:00.000000', '2026-12-10 18:00:00.000000', :paid, :approver)"
                ), {"id": app_id.hex, "employee": employee_id.hex, "leave_type": leave_type_id.hex,
                    "number": f"LV-{index:02}", "paid": 30 - index,
                    "approver": approver_id.hex if index < 27 else None})
                app = SimpleNamespace(
                    id=app_id, application_no=f"LV-{index:02}", paid_minutes=30 - index,
                    start_at=datetime(2026, 12, 10, 9, tzinfo=ZoneInfo("Asia/Manila")),
                    end_at=datetime(2026, 12, 10, 18, tzinfo=ZoneInfo("Asia/Manila")),
                )
                records[app_id] = (app, SimpleNamespace(employee_no=f"E{index:02}", first_name=name, last_name="Test"),
                                   SimpleNamespace(leave_name="Vacation"))

            async def execute(statement):
                ids = connection.scalars(statement.with_only_columns(LeaveApplicationModel.id, maintain_column_froms=True)).all()
                return SimpleNamespace(all=lambda: [records[app_id] for app_id in ids])

            session = SimpleNamespace(execute=execute)
            actor = ApprovalReturnActor(uuid4(), uuid4(), True)
            async def page(offset, key, direction):
                return (await list_approved_leave_for_reversal(
                    date(2026, 12, 1), date(2026, 12, 31), offset, actor, UnitOfWork(session), key, direction,
                )).data
            first = await page(0, "employee", "asc")
            second = await page(25, "employee", "asc")
            self.assertEqual(first.next_offset, 25)
            self.assertIsNone(second.next_offset)
            self.assertEqual([row.employee_name for row in first.items + second.items],
                             [f"Employee {index:02} Test" for index in range(30)])
            descending = await page(0, "employee", "desc")
            self.assertEqual(descending.items[0].employee_name, "Employee 29 Test")
            paid = await page(0, "paid_minutes", "asc")
            self.assertEqual([row.paid_minutes for row in paid.items], list(range(1, 26)))
            actor = ApprovalReturnActor(approver_id, uuid4(), False)
            first, second = await page(0, "application", "asc"), await page(25, "application", "asc")
            self.assertEqual([row.application_no for row in first.items + second.items],
                             [f"LV-{index:02}" for index in range(27)])
            actor = ApprovalReturnActor(uuid4(), uuid4(), False)
            self.assertEqual((await page(0, "application", "asc")).items, [])
        finally:
            connection.close()
            engine.dispose()

    async def test_only_active_hr_admin_in_hr_dashboard_can_access(self):
        claims = {"sub": str(uuid4()), "email": "hr@example.invalid"}
        employee_id = uuid4()
        auth = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            role_codes=["HR_ADMIN"], employee_id=employee_id,
        )))
        self.assertEqual(await require_hr_dashboard_access("HR_ADMIN", claims, auth), (UUID(claims["sub"]), employee_id))
        for role_codes, mode, profile in [
            (["SYSTEM_ADMIN"], "HR_ADMIN", employee_id),
            (["HR_ADMIN"], "EMPLOYEE", employee_id),
            (["HR_ADMIN"], "HR_ADMIN", None),
        ]:
            auth.execute.return_value = SimpleNamespace(role_codes=role_codes, employee_id=profile)
            with self.assertRaises(HTTPException) as error:
                await require_hr_dashboard_access(mode, claims, auth)
            self.assertEqual(error.exception.status_code, 403)

    async def test_return_scope_uses_live_role_not_client_claims(self):
        user_id, employee_id = uuid4(), uuid4()
        claims = {"sub": str(user_id), "email": "approver@example.invalid", "role_codes": ["HR_ADMIN"]}
        auth = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            role_codes=["SUPERVISOR"], employee_id=employee_id,
        )))
        self.assertEqual(await require_approval_return_access("SUPERVISOR", claims, auth),
                         ApprovalReturnActor(user_id, employee_id, False))
        with self.assertRaises(HTTPException):
            await require_approval_return_access("HR_ADMIN", claims, auth)
        auth.execute.return_value.role_codes = ["SUPERVISOR", "HR_ADMIN"]
        self.assertFalse((await require_approval_return_access("SUPERVISOR", claims, auth)).organization_wide)
        self.assertTrue((await require_approval_return_access("HR_ADMIN", claims, auth)).organization_wide)

    async def test_supervisor_can_only_return_their_own_decision(self):
        for approved_by in (None, uuid4()):
            application, _, _, session = fixture()
            application.approved_by_id = approved_by
            with self.assertRaisesRegex(ValueError, "personally approved"):
                await leave.LeaveApplicationUseCase(UnitOfWork(session)).return_approved_to_pending(
                    application.id, uuid4(), uuid4(), "Correction", original_approver_only=True,
                )
            session.add.assert_not_called()
        application, _, _, session = fixture()
        actor_id = application.approved_by_id
        with patch.object(leave, "require_attendance_open", new=AsyncMock()), \
                patch.object(leave, "assign_org_approval", new=AsyncMock()), \
                patch.object(leave, "_to_entity", side_effect=lambda model, _: model):
            await leave.LeaveApplicationUseCase(UnitOfWork(session)).return_approved_to_pending(
                application.id, actor_id, uuid4(), "Correction", original_approver_only=True,
            )
        self.assertEqual(application.status, "PENDING")
        self.assertIsNone(application.approved_by_id)

    async def test_return_endpoint_passes_server_authorized_scope(self):
        for organization_wide in (False, True):
            actor = ApprovalReturnActor(uuid4(), uuid4(), organization_wide)
            use_case = SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
                return_approved_to_pending=AsyncMock(side_effect=ValueError("Blocked")),
            )
            with self.assertRaises(HTTPException):
                await return_approved_leave_for_approval(
                    uuid4(), LeaveReversalRequest(reason="Correction"), actor, use_case, None,
                )
            self.assertEqual(use_case.return_approved_to_pending.await_args.kwargs,
                             {"original_approver_only": not organization_wide})

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
