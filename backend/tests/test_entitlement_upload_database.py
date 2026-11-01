import asyncio
import importlib.util
import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateColumn

from app.auth.infrastructure.dependencies import (
    get_current_authorization_use_case,
    get_current_user_claims,
)
from app.core.database import init_db_models
from app.core.generics.uow import GenUnitOfWork, get_unit_of_work
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.leaves.application.entitlement_upload_use_case import (
    EntitlementUploadChangedError,
    EntitlementUploadInvalidError,
    EntitlementUploadUseCase,
)
from app.filemaintenance.leaves.application.leave_records_use_case import EmployeeEntitlementUseCase
from app.filemaintenance.leaves.infrastructure.db_model import LeaveTypeModel
from app.filemaintenance.leaves.infrastructure.leave_records_db_model import EmployeeEntitlementModel
from app.filemaintenance.leaves.infrastructure.leave_records_router import entitlements_router
from backend.tests.test_entitlement_upload import csv_file

if importlib.util.find_spec("httpx") is not None:
    import httpx
else:
    httpx = None

TEST_DATABASE_URL = os.getenv("ENTITLEMENT_UPLOAD_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "Requires an empty, disposable entitlement upload test database.")
class EntitlementUploadDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if TEST_DATABASE_URL is None:
            self.skipTest("Requires a disposable entitlement upload test database.")
        url = make_url(TEST_DATABASE_URL)
        if not (url.database or "").startswith("entitlement_upload_test_"):
            raise RuntimeError("Tests require an empty entitlement_upload_test_* database.")
        init_db_models()
        self.engine = create_async_engine(url)
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as connection:
            existing = await connection.exec_driver_sql(
                "SELECT to_regnamespace('hr'), to_regnamespace('leave_mgmt')"
            )
            if any(existing.one()):
                raise RuntimeError("The disposable entitlement upload test database must be empty.")
            await connection.exec_driver_sql("CREATE SCHEMA hr")
            await connection.exec_driver_sql("CREATE SCHEMA leave_mgmt")
            self.addAsyncCleanup(self.drop_test_schemas)
            for model in (EmployeeModel, EmploymentAssignmentModel, LeaveTypeModel, EmployeeEntitlementModel):
                table = model.__table__
                columns = ", ".join(
                    str(CreateColumn(column).compile(dialect=postgresql.dialect()))
                    for column in table.columns
                )
                unique = (
                    ", CONSTRAINT uq_employee_entitlements_employee_type_year "
                    "UNIQUE (employee_id, leave_type_id, entitlement_year)"
                    if model is EmployeeEntitlementModel else ""
                )
                await connection.exec_driver_sql(
                    f"CREATE TABLE {table.schema}.{table.name} ({columns}, PRIMARY KEY (id){unique})"
                )
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.employee_a, self.employee_b = uuid4(), uuid4()
        self.company_a, self.company_b = uuid4(), uuid4()
        self.leave_a, self.leave_b = uuid4(), uuid4()
        self.existing_id = uuid4()
        async with self.factory.begin() as session:
            session.add_all([
                EmployeeModel(id=self.employee_a, employee_no="0001", first_name="Ana", last_name="Cruz"),
                EmployeeModel(id=self.employee_b, employee_no="E002", first_name="Ben", last_name="Lim"),
                EmploymentAssignmentModel(
                    id=uuid4(), employee_id=self.employee_a, company_id=self.company_a,
                    primary_location_id=uuid4(), employment_type="REGULAR", employee_category="REGULAR",
                    hire_date=date(2020, 1, 1), effective_from=date(2020, 1, 1),
                ),
                EmploymentAssignmentModel(
                    id=uuid4(), employee_id=self.employee_b, company_id=self.company_b,
                    primary_location_id=uuid4(), employment_type="REGULAR", employee_category="REGULAR",
                    hire_date=date(2020, 1, 1), effective_from=date(2020, 1, 1),
                ),
                LeaveTypeModel(
                    id=self.leave_a, company_id=self.company_a, leave_code="VL", leave_name="Vacation",
                    leave_category="VACATION", unit_type="DAYS", accrual_method="NONE",
                    effective_from=date(2020, 1, 1),
                ),
                LeaveTypeModel(
                    id=self.leave_b, company_id=self.company_b, leave_code="VL", leave_name="Vacation",
                    leave_category="VACATION", unit_type="HOURS", accrual_method="NONE",
                    effective_from=date(2020, 1, 1),
                ),
                EmployeeEntitlementModel(
                    id=self.existing_id, employee_id=self.employee_a, leave_type_id=self.leave_a,
                    entitlement_year=2026, granted_minutes=4800, used_minutes=480, available_minutes=4320,
                ),
            ])

    async def drop_test_schemas(self):
        async with self.engine.begin() as connection:
            await connection.exec_driver_sql("DROP SCHEMA IF EXISTS leave_mgmt CASCADE")
            await connection.exec_driver_sql("DROP SCHEMA IF EXISTS hr CASCADE")

    def use_case(self):
        return EntitlementUploadUseCase(GenUnitOfWork(self.factory))

    async def test_real_postgres_creates_and_updates_multiple_employee_balances(self):
        content = csv_file(
            {"employee_no": "0001", "granted": "12", "used": "2"},
            {"employee_no": "E002", "granted": "8", "used": "2"},
        )
        preview = await self.use_case().preview(content)
        self.assertTrue(preview.is_valid)
        self.assertEqual([row.action for row in preview.rows], ["UPDATE", "CREATE"])
        result = await self.use_case().apply(content, preview.preview_token)
        self.assertEqual([change.action for change in result.changes], ["UPDATE", "CREATE"])
        async with self.factory() as session:
            records = (await session.execute(select(EmployeeEntitlementModel))).scalars().all()
        by_employee = {record.employee_id: record for record in records}
        self.assertEqual(len(by_employee), 2)
        self.assertEqual((by_employee[self.employee_a].used_minutes, by_employee[self.employee_a].available_minutes), (960, 4800))
        self.assertEqual((by_employee[self.employee_b].granted_minutes, by_employee[self.employee_b].available_minutes), (480, 360))

    @unittest.skipIf(httpx is None, "The HTTP integration test requires the optional httpx test dependency.")
    async def test_http_upload_uses_real_dependency_wiring_and_persists_balances(self):
        app = FastAPI()
        app.include_router(entitlements_router)
        actor_id = uuid4()
        authorization = SimpleNamespace(execute=AsyncMock(
            return_value=SimpleNamespace(permission_codes=["leave.manage"])
        ))
        app.dependency_overrides.update({
            get_current_user_claims: lambda: {"sub": str(actor_id), "email": "hr@example.invalid"},
            get_current_authorization_use_case: lambda: authorization,
            get_unit_of_work: lambda: GenUnitOfWork(self.factory),
        })
        content = csv_file({"granted": "12", "used": "2"}, {"employee_no": "E002", "granted": "8"})
        with patch("app.filemaintenance.leaves.infrastructure.leave_records_router._queue_leave_dashboard_refresh") as refresh:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                template = await client.get("/employee-entitlements/upload/template")
                self.assertEqual(template.status_code, 200)
                preview = await client.post(
                    "/employee-entitlements/upload/preview",
                    files={"file": ("balances.csv", content, "text/csv")},
                )
                self.assertEqual(preview.status_code, 200)
                data = preview.json()["data"]
                self.assertTrue(data["is_valid"])
                response = await client.post(
                    "/employee-entitlements/upload",
                    data={"preview_token": data["preview_token"]},
                    files={"file": ("balances.csv", content, "text/csv")},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()["data"]["created"], response.json()["data"]["updated"]), (1, 1))
        self.assertEqual(refresh.call_count, 2)
        async with self.factory() as session:
            record = await session.get(EmployeeEntitlementModel, self.existing_id)
        self.assertEqual((record.granted_minutes, record.used_minutes, record.available_minutes), (5760, 960, 4800))

    async def test_existing_manual_entitlement_update_still_uses_shared_eligibility_rules(self):
        use_case = EmployeeEntitlementUseCase(GenUnitOfWork(self.factory))
        result = await use_case.update(self.existing_id, {"granted_minutes": 5760})
        self.assertEqual((result.used_minutes, result.available_minutes), (480, 5280))

    async def test_real_postgres_rejects_an_older_version_with_the_same_code(self):
        old_type = LeaveTypeModel(
            id=uuid4(), company_id=self.company_a, leave_code="VL", leave_name="Old vacation",
            leave_category="VACATION", unit_type="DAYS", accrual_method="NONE",
            effective_from=date(2019, 1, 1), is_active=False, status="INACTIVE",
        )
        async with self.factory.begin() as session:
            session.add(old_type)
            existing = await session.get(EmployeeEntitlementModel, self.existing_id)
            existing.leave_type_id = old_type.id
        content = csv_file({"granted": "12"})
        preview = await self.use_case().preview(content)
        self.assertFalse(preview.is_valid)
        self.assertIn("another version", " ".join(preview.rows[0].errors))
        with self.assertRaises(EntitlementUploadInvalidError):
            await self.use_case().apply(content, "0" * 64)
        async with self.factory() as session:
            records = (await session.execute(select(EmployeeEntitlementModel))).scalars().all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].leave_type_id, old_type.id)

    async def test_same_code_from_another_company_is_not_overwritten(self):
        async with self.factory.begin() as session:
            existing = await session.get(EmployeeEntitlementModel, self.existing_id)
            existing.leave_type_id = self.leave_b
        content = csv_file({"granted": "12"})
        preview = await self.use_case().preview(content)
        self.assertTrue(preview.is_valid)
        self.assertEqual(preview.rows[0].action, "CREATE")
        await self.use_case().apply(content, preview.preview_token)
        async with self.factory() as session:
            records = (await session.execute(select(EmployeeEntitlementModel))).scalars().all()
        self.assertEqual(len(records), 2)
        old = next(record for record in records if record.id == self.existing_id)
        self.assertEqual((old.leave_type_id, old.granted_minutes), (self.leave_b, 4800))

    async def test_concurrent_updates_cannot_overwrite_a_stale_preview(self):
        files = [csv_file({"granted": "12"}), csv_file({"granted": "15"})]
        previews = [await self.use_case().preview(content) for content in files]
        outcomes = await asyncio.wait_for(asyncio.gather(
            *(self.use_case().apply(content, preview.preview_token) for content, preview in zip(files, previews)),
            return_exceptions=True,
        ), timeout=10)
        self.assertEqual(sum(isinstance(item, EntitlementUploadChangedError) for item in outcomes), 1)
        self.assertEqual(sum(not isinstance(item, Exception) for item in outcomes), 1)
        async with self.factory() as session:
            record = await session.get(EmployeeEntitlementModel, self.existing_id)
        self.assertIn(record.granted_minutes, {5760, 7200})

    async def test_concurrent_creates_never_duplicate_or_partially_apply(self):
        files = [
            csv_file(
                {"entitlement_year": "2027", "granted": "12"},
                {"entitlement_year": "2026", "granted": "11", "used": "1"},
            ),
            csv_file(
                {"entitlement_year": "2027", "granted": "15"},
                {"employee_no": "E002", "entitlement_year": "2026", "granted": "8"},
            ),
        ]
        previews = [await self.use_case().preview(content) for content in files]
        barrier = asyncio.Barrier(2)

        class SynchronizedSession(AsyncSession):
            async def execute(self, statement, *args, **kwargs):
                result = await super().execute(statement, *args, **kwargs)
                if (
                    statement.column_descriptions[0].get("entity") is EmployeeEntitlementModel
                    and statement._for_update_arg is not None
                ):
                    await barrier.wait()
                return result

        factory = async_sessionmaker(self.engine, class_=SynchronizedSession, expire_on_commit=False)
        outcomes = await asyncio.wait_for(asyncio.gather(
            *(EntitlementUploadUseCase(GenUnitOfWork(factory)).apply(content, preview.preview_token)
              for content, preview in zip(files, previews)),
            return_exceptions=True,
        ), timeout=10)
        self.assertEqual(sum(isinstance(item, EntitlementUploadChangedError) for item in outcomes), 1, outcomes)
        self.assertEqual(sum(not isinstance(item, Exception) for item in outcomes), 1, outcomes)
        async with self.factory() as session:
            records = (await session.execute(
                select(EmployeeEntitlementModel).where(EmployeeEntitlementModel.entitlement_year == 2027)
            )).scalars().all()
            existing = await session.get(EmployeeEntitlementModel, self.existing_id)
            second = (await session.execute(
                select(EmployeeEntitlementModel).where(EmployeeEntitlementModel.employee_id == self.employee_b)
            )).scalars().all()
        self.assertEqual(len(records), 1)
        self.assertIn(records[0].granted_minutes, {5760, 7200})
        if isinstance(outcomes[0], EntitlementUploadChangedError):
            self.assertEqual(existing.granted_minutes, 4800)
            self.assertEqual(len(second), 1)
            self.assertEqual(second[0].granted_minutes, 480)
        else:
            self.assertEqual(existing.granted_minutes, 5280)
            self.assertEqual(second, [])
