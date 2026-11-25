import unittest
import os
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import select

from app.attendance.infrastructure.offline_gateway import TransactionAttendanceUow
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.auth.application.authorization import CurrentAuthorization
from app.auth.infrastructure.db_model import UserModel
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.core.database import AsyncSessionLocal, engine, init_db_models
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel
from app.filemaintenance.leaves.application.leave_records_use_case import (
    EmployeeEntitlementUseCase,
    LeaveApplicationUseCase,
    LeaveLedgerUseCase,
    _validate_entitlement_grant,
)
from app.filemaintenance.leaves.domain.entities.leave_records import EmployeeEntitlementEntity
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import (
    EmployeeEntitlementModel,
    LeaveApplicationModel,
    LeaveLedgerModel,
)
from app.filemaintenance.leaves.infrastructure.leave_records_dependencies import get_employee_entitlement_use_case
from app.filemaintenance.leaves.infrastructure.leave_records_router import entitlements_router
from app.filemaintenance.schedule.infrastructure.db_model import ScheduleTemplateModel


class QueryResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class EmployeeEntitlementEligibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_grant_allowed_after_minimum_service_months(self) -> None:
        company_id = uuid4()
        employee_id = uuid4()
        leave_type_id = uuid4()
        assignment = SimpleNamespace(
            company_id=company_id,
            hire_date=date(2025, 4, 9),
            primary_location_id=uuid4(),
        )
        leave_type = SimpleNamespace(
            company_id=company_id,
            is_active=True,
            status="ACTIVE",
            effective_from=date(2025, 1, 1),
            effective_to=None,
            minimum_service_months=6,
        )
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[QueryResult(assignment), QueryResult(leave_type)])
        )

        await _validate_entitlement_grant(
            session,
            employee_id,
            leave_type_id,
            date(2025, 10, 9),
        )

    async def test_grant_rejected_before_minimum_service_months(self) -> None:
        company_id = uuid4()
        assignment = SimpleNamespace(
            company_id=company_id,
            hire_date=date(2025, 4, 10),
            primary_location_id=uuid4(),
        )
        leave_type = SimpleNamespace(
            company_id=company_id,
            is_active=True,
            status="ACTIVE",
            effective_from=date(2025, 1, 1),
            effective_to=None,
            minimum_service_months=6,
        )
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[QueryResult(assignment), QueryResult(leave_type)])
        )

        with self.assertRaisesRegex(ValueError, "completed 5 of 6 required service months"):
            await _validate_entitlement_grant(
                session,
                uuid4(),
                uuid4(),
                date(2025, 10, 9),
            )

    async def test_grant_rejected_when_leave_type_belongs_to_another_company(self) -> None:
        assignment = SimpleNamespace(
            company_id=uuid4(),
            hire_date=date(2020, 1, 1),
            primary_location_id=uuid4(),
        )
        leave_type = SimpleNamespace(company_id=uuid4())
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[QueryResult(assignment), QueryResult(leave_type)])
        )

        with self.assertRaisesRegex(ValueError, "does not belong to the employee's assigned company"):
            await _validate_entitlement_grant(
                session,
                uuid4(),
                uuid4(),
                date(2025, 10, 9),
            )


class EntitlementDeleteHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_requires_leave_manage_and_reports_conflicts(self):
        actor_id, entitlement_id, employee_id = uuid4(), uuid4(), uuid4()
        claims = {"sub": str(actor_id), "email": "hr@example.invalid"}
        authorization = SimpleNamespace(execute=AsyncMock(
            return_value=CurrentAuthorization([], [], None, employee_id),
        ))
        entitlement = EmployeeEntitlementEntity(
            id=entitlement_id, employee_id=employee_id, leave_type_id=uuid4(), entitlement_year=2026,
        )
        use_case = SimpleNamespace(delete=AsyncMock(return_value=entitlement))
        app = FastAPI()
        app.include_router(entitlements_router)
        app.dependency_overrides.update({
            get_current_user_claims: lambda: claims,
            get_current_authorization_use_case: lambda: authorization,
            get_employee_entitlement_use_case: lambda: use_case,
            get_audit_es_client: lambda: None,
        })

        async def request():
            messages = []
            delivered = False

            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                return {"type": "http.disconnect"}

            async def send(message):
                messages.append(message)

            path = f"/employee-entitlements/{entitlement_id}"
            await app({
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": "DELETE", "scheme": "http", "path": path,
                "raw_path": path.encode(), "query_string": b"", "headers": [],
                "server": ("test", 80), "client": ("test", 1234), "root_path": "",
            }, receive, send)
            return next(message["status"] for message in messages if message["type"] == "http.response.start")

        self.assertEqual(await request(), 403)
        use_case.delete.assert_not_awaited()
        authorization.execute.return_value = CurrentAuthorization([], ["leave.manage"], None, employee_id)
        with patch("app.filemaintenance.leaves.infrastructure.leave_records_router._queue_leave_dashboard_refresh") as refresh:
            self.assertEqual(await request(), 200)
            refresh.assert_called_once_with(employee_id)
            use_case.delete.side_effect = ValueError("This entitlement cannot be deleted because it has leave activity.")
            self.assertEqual(await request(), 409)
            use_case.delete.side_effect = None
            use_case.delete.return_value = None
            self.assertEqual(await request(), 404)


@unittest.skipUnless(os.getenv("RUN_ENTITLEMENT_DELETE_DB_TESTS") == "1", "Requires a migrated test database.")
class EntitlementDeleteDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        init_db_models()
        self.session = AsyncSessionLocal()
        self.addAsyncCleanup(engine.dispose)
        self.addAsyncCleanup(self.session.close)
        self.addAsyncCleanup(self.session.rollback)
        await self.session.begin()
        company_id = await self.session.scalar(select(ScheduleTemplateModel.company_id).limit(1))
        if company_id is None:
            self.skipTest("Requires a company with a schedule template.")
        self.employee_id, self.user_id, self.leave_type_id, self.entitlement_id = (
            uuid4(), uuid4(), uuid4(), uuid4()
        )
        self.session.add(EmployeeModel(
            id=self.employee_id, employee_no="TEST-" + uuid4().hex[:16],
            first_name="Synthetic", last_name="Test",
        ))
        await self.session.flush()
        self.session.add(UserModel(
            id=self.user_id, employee_id=self.employee_id, username="test-" + uuid4().hex,
            password_hash="synthetic", account_status="ACTIVE",
        ))
        self.session.add(LeaveTypeModel(
            id=self.leave_type_id, company_id=company_id, leave_code="T" + uuid4().hex[:12],
            leave_name="Synthetic", leave_category="VACATION", unit_type="DAYS",
            accrual_method="NONE", effective_from=date(2020, 1, 1),
        ))
        await self.session.flush()
        self.entitlement = EmployeeEntitlementModel(
            id=self.entitlement_id, employee_id=self.employee_id, leave_type_id=self.leave_type_id,
            entitlement_year=2026, granted_minutes=480, available_minutes=480,
        )
        self.session.add(self.entitlement)
        await self.session.flush()
        self.use_case = EmployeeEntitlementUseCase(TransactionAttendanceUow(self.session))

    async def test_unused_entitlement_is_deleted(self):
        start = datetime(2025, 12, 31, 15, 0, tzinfo=timezone.utc)
        self.session.add(LeaveApplicationModel(
            application_no="TEST-" + uuid4().hex, employee_id=self.employee_id,
            leave_type_id=self.leave_type_id, start_at=start, end_at=start + timedelta(hours=1),
            duration_type="FULL_DAY", requested_minutes=60, reason="Synthetic", status="DRAFT",
        ))
        self.session.add(LeaveLedgerModel(
            employee_id=self.employee_id, leave_type_id=self.leave_type_id,
            transaction_date=date(2025, 12, 31), transaction_type="LEAVE_USED",
            reference_type="LEAVE_APPLICATION", minutes_delta=-60,
            balance_after_minutes=420, posted_by=self.user_id,
        ))
        await self.session.flush()
        deleted = await self.use_case.delete(self.entitlement_id)
        self.assertEqual(deleted.id, self.entitlement_id)
        self.assertIsNone(await self.session.get(EmployeeEntitlementModel, self.entitlement_id))
        self.assertIsNone(await self.use_case.delete(self.entitlement_id))

    async def test_application_at_manila_year_boundary_blocks_deletion(self):
        start = datetime(2025, 12, 31, 15, 30, tzinfo=timezone.utc)
        with (
            patch("app.filemaintenance.leaves.application.leave_records_use_case._validate_leave_type_company", new=AsyncMock()),
            patch("app.filemaintenance.leaves.application.leave_records_use_case._require_leave_open", new=AsyncMock()),
        ):
            application = await LeaveApplicationUseCase(TransactionAttendanceUow(self.session)).create({
                "application_no": "TEST-" + uuid4().hex, "employee_id": self.employee_id,
                "leave_type_id": self.leave_type_id, "start_at": start, "end_at": start + timedelta(hours=1),
                "duration_type": "FULL_DAY", "requested_minutes": 60, "reason": "Synthetic", "status": "DRAFT",
            })
        model = await self.session.get(LeaveApplicationModel, application.id)
        model.status = "CANCELLED"
        model.is_active = False
        await self.session.flush()
        with self.assertRaisesRegex(ValueError, "leave activity"):
            await self.use_case.delete(self.entitlement_id)
        self.assertIsNotNone(await self.session.get(EmployeeEntitlementModel, self.entitlement_id))

    async def test_ledger_and_used_balance_block_deletion(self):
        self.entitlement.used_minutes = 60
        await self.session.flush()
        with self.assertRaisesRegex(ValueError, "leave activity"):
            await self.use_case.delete(self.entitlement_id)
        self.entitlement.used_minutes = 0
        await LeaveLedgerUseCase(TransactionAttendanceUow(self.session)).create({
            "employee_id": self.employee_id, "leave_type_id": self.leave_type_id,
            "transaction_date": date(2026, 11, 25), "transaction_type": "LEAVE_USED",
            "reference_type": "LEAVE_APPLICATION", "minutes_delta": -60,
            "balance_after_minutes": 420, "posted_by": self.user_id,
        })
        with self.assertRaisesRegex(ValueError, "leave activity"):
            await self.use_case.delete(self.entitlement_id)
        self.assertIsNotNone(await self.session.get(EmployeeEntitlementModel, self.entitlement_id))
