import asyncio
import csv
import os
import unittest
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import engine
from app.core.generics.uow import GenUnitOfWork
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.core.generics.uow import get_unit_of_work
from app.filemaintenance.employees.application.employee_export import (
    EMPLOYEE_EXPORT_FIELDS, PERSONAL_DETAILS_EXPORT_FIELDS,
)
from app.filemaintenance.employees.application.personal_details import (
    EmployeePersonalDetailsInput,
    plan_personal_details_fill,
    save_personal_details,
)
from app.filemaintenance.employees.application.use_case import (
    CreateEmployeeUseCase,
    UpdateEmployeeUseCase,
)
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmployeePersonalDetailsModel,
)
from app.filemaintenance.employees.infrastructure.personal_details_router import (
    PersonalDetailsImportInput,
    get_personal_details,
    get_personal_details_template_example,
    import_personal_details,
    router,
)


class PersonalDetailsTests(unittest.TestCase):
    def test_fill_preserves_existing_values_and_ignores_blank_cells(self):
        existing = EmployeePersonalDetailsModel(bank_account_no="000123", sss_no=None, tin_no="123")
        changes, conflicts = plan_personal_details_fill(existing, EmployeePersonalDetailsInput(
            bank_account_no="999", sss_no=" 000456 ", tin_no=" ", province="Metro Manila",
        ))
        self.assertEqual(changes, {"sss_no": "000456", "province": "Metro Manila"})
        self.assertEqual(conflicts, ["bank_account_no"])
        self.assertEqual(existing.bank_account_no, "000123")

    def test_identical_values_are_idempotent(self):
        existing = EmployeePersonalDetailsModel(sss_no="001234")
        self.assertEqual(
            plan_personal_details_fill(existing, EmployeePersonalDetailsInput(sss_no="001234")),
            ({}, []),
        )

    def test_invalid_status_unknown_fields_and_numeric_identifiers_are_rejected(self):
        for payload in ({"civil_status": "INVALID"}, {"sss_no": 123}, {"unknown": "value"}, {"tin_no": "1" * 31}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                EmployeePersonalDetailsInput.model_validate(payload)

    def test_import_limits_and_missing_employee_number_are_rejected(self):
        for rows in ([], [{"employee_no": ""}], [{"employee_no": "E"}] * 501):
            with self.subTest(count=len(rows)), self.assertRaises(ValidationError):
                PersonalDetailsImportInput(rows=rows)

    def test_psgc_codes_must_have_nine_digits(self):
        self.assertEqual(EmployeePersonalDetailsInput(psgc_region_code="010000000").psgc_region_code, "010000000")
        for code in ("12345678", "1234567890", "abcdefghi"):
            with self.subTest(code=code), self.assertRaises(ValidationError):
                EmployeePersonalDetailsInput(psgc_city_code=code)


class PersonalDetailsPermissionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_read_and_import_require_employee_management(self):
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            permission_codes=["employees.read", "employees.read_team"],
        )))
        for route in router.routes:
            permission = route.dependant.dependencies[0].call
            with self.subTest(path=route.path), self.assertRaises(HTTPException) as error:
                await permission(claims={"sub": str(uuid4())}, use_case=authorization)
            self.assertEqual(error.exception.status_code, 403)


class EmployeeExportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor_id = uuid4()
        self.authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            role_codes=["HR_ADMIN"], permission_codes=["employees.manage"],
        )))
        self.rows = []
        self.session = SimpleNamespace(execute=AsyncMock(
            side_effect=lambda statement: SimpleNamespace(all=lambda: self.rows),
        ))
        session = self.session

        class FakeUow:
            async def __aenter__(self):
                self.session = session
                return self

            async def __aexit__(self, *args):
                return False

        app = FastAPI()
        app.include_router(router, prefix="/employees")
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(self.actor_id), "role_codes": ["HR_ADMIN"],
        }
        app.dependency_overrides[get_current_authorization_use_case] = lambda: self.authorization
        app.dependency_overrides[get_unit_of_work] = FakeUow
        app.dependency_overrides[get_audit_es_client] = lambda: None
        self.app = app

    async def download(self, role="HR_ADMIN"):
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": "/employees/export",
            "raw_path": b"/employees/export", "root_path": "",
            "query_string": f"dashboard_role_code={role}".encode() if role else b"",
            "headers": [], "server": ("localhost", 80), "client": ("127.0.0.1", 1234),
        }
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await self.app(scope, receive, send)
        return SimpleNamespace(
            status_code=messages[0]["status"],
            headers={key.decode(): value.decode() for key, value in messages[0]["headers"]},
            content=b"".join(message.get("body", b"") for message in messages),
        )

    async def test_current_hr_role_permission_and_selected_mode_are_all_required(self):
        for roles, permissions, selected in (
            (["SYSTEM_ADMIN"], ["employees.manage"], "HR_ADMIN"),
            (["SUPERVISOR"], ["employees.manage"], "HR_ADMIN"),
            ([], ["employees.manage"], "HR_ADMIN"),
            (["HR_ADMIN"], ["employees.read"], "HR_ADMIN"),
            (["HR_ADMIN", "SUPERVISOR"], ["employees.manage"], "SUPERVISOR"),
        ):
            self.authorization.execute.return_value = SimpleNamespace(
                role_codes=roles, permission_codes=permissions,
            )
            with self.subTest(roles=roles, selected=selected):
                self.assertEqual((await self.download(selected)).status_code, 403)
        self.session.execute.assert_not_awaited()

    async def test_csv_includes_all_profile_fields_addresses_and_employees_without_details(self):
        headers = (*EMPLOYEE_EXPORT_FIELDS, *PERSONAL_DETAILS_EXPORT_FIELDS)
        saved = {
            "employee_no": "000123", "first_name": "Synthetic", "last_name": "Employee",
            "bank_account_no": "000456", "sss_no": "001234", "pagibig_no": "000789",
            "philhealth_no": "000987", "tin_no": "000321", "civil_status": "SINGLE",
            "address_line_1": 'Unit 1, "Sample" Street', "address_line_2": "Floor 2\nBuilding A",
            "region": "Test region", "province": "Test province",
            "city_municipality": "Test city", "barangay": "Test barangay",
            "postal_code": "0100", "psgc_region_code": "010000000",
            "psgc_province_code": "010010000", "psgc_city_code": "010010100",
            "psgc_barangay_code": "010010101", "record_status": "ARCHIVED", "is_active": False,
        }
        self.rows = [
            tuple(saved.get(field) for field in headers),
            tuple("LEGACY" if field == "employee_no" else None for field in headers),
        ]
        with patch(
            "app.filemaintenance.employees.infrastructure.personal_details_router.log_entity_action",
            new=AsyncMock(),
        ) as audit:
            response = await self.download()
        self.assertEqual(audit.await_args.kwargs["after"], {"row_count": 2})
        self.assertEqual(audit.await_args.kwargs["action"], "EXPORT")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn('filename="employees.csv"', response.headers["content-disposition"])
        rows = list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"), newline="")))
        for field, value in saved.items():
            self.assertEqual(rows[0][field], str(value))
        self.assertEqual(rows[1]["employee_no"], "LEGACY")
        self.assertEqual(rows[1]["address_line_1"], "")
        statement = self.session.execute.await_args.args[0]
        self.assertIn("LEFT OUTER JOIN", str(statement))
        self.assertIsNone(statement.whereclause)
        self.assertEqual((await self.download(None)).status_code, 422)

    async def test_empty_export_has_headers_and_formula_values_are_neutralized(self):
        headers = (*EMPLOYEE_EXPORT_FIELDS, *PERSONAL_DETAILS_EXPORT_FIELDS)
        response = await self.download()
        self.assertEqual(list(csv.reader(StringIO(response.content.decode("utf-8-sig")))), [list(headers)])
        for value in ("=1+1", " +cmd", "-1", "@SUM(1,1)", "\tcmd", "\rcmd", "\ncmd"):
            self.rows = [tuple(value if field == "address_line_1" else None for field in headers)]
            response = await self.download()
            rows = list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"), newline="")))
            self.assertEqual(rows[0]["address_line_1"], "'" + value)


TEST_DATABASE_NAME = os.getenv("EMPLOYEE_DETAILS_TEST_DATABASE_NAME", "")


@unittest.skipUnless(TEST_DATABASE_NAME, "Set EMPLOYEE_DETAILS_TEST_DATABASE_NAME to a disposable database.")
class PersonalDetailsDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not TEST_DATABASE_NAME.startswith("employee_details_test_"):
            self.fail("Only a disposable employee_details_test_* database may be used.")
        self.test_engine = create_async_engine(engine.url.set(database=TEST_DATABASE_NAME))
        async with self.test_engine.begin() as connection:
            await connection.execute(text("CREATE SCHEMA IF NOT EXISTS hr"))
            await connection.run_sync(lambda sync: EmployeeModel.__table__.create(sync, checkfirst=True))
            raw = await connection.get_raw_connection()
            migration = Path(__file__).resolve().parents[1] / "sql" / "20261112_create_employee_personal_details.sql"
            # Execute only the DDL inside the surrounding SQLAlchemy transaction.
            ddl = migration.read_text().removeprefix("BEGIN;").strip().removesuffix("COMMIT;")
            await raw.driver_connection.execute(ddl)
            await raw.driver_connection.execute(ddl)
            migration_employee_id = uuid4()
            await connection.execute(
                text("INSERT INTO hr.employees (id, employee_no, first_name, last_name) VALUES (:id, :no, 'Legacy', 'Test')"),
                {"id": migration_employee_id, "no": f"MIG-{migration_employee_id.hex[:12]}"},
            )
            await connection.execute(
                text("INSERT INTO hr.employee_personal_details (employee_id, province, city_municipality, barangay) VALUES (:id, 'Old province', 'Old city', 'Old barangay')"),
                {"id": migration_employee_id},
            )
            migration = Path(__file__).resolve().parents[1] / "sql" / "20261112_add_employee_psgc_address.sql"
            ddl = migration.read_text().removeprefix("BEGIN;").strip().removesuffix("COMMIT;")
            await raw.driver_connection.execute(ddl)
            await raw.driver_connection.execute(ddl)
            legacy = (await connection.execute(
                text("SELECT province, city_municipality, barangay, psgc_region_code FROM hr.employee_personal_details WHERE employee_id = :id"),
                {"id": migration_employee_id},
            )).one()
            self.assertEqual(tuple(legacy), ("Old province", "Old city", "Old barangay", None))
            await connection.execute(text("DELETE FROM hr.employees WHERE id = :id"), {"id": migration_employee_id})
        self.connection = await self.test_engine.connect()
        self.transaction = await self.connection.begin()
        self.factory = async_sessionmaker(
            bind=self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
        )
        self.actor_id = uuid4()
        self.claims = {"sub": str(self.actor_id)}
        self.stack = ExitStack()
        module = "app.filemaintenance.employees.application.use_case."
        self.stack.enter_context(patch(module + "find_user_conflict", AsyncMock(return_value=False)))
        self.stack.enter_context(patch(module + "create_user_account", AsyncMock()))
        self.stack.enter_context(patch(module + "sync_user_account_with_employee", AsyncMock()))
        self.stack.enter_context(patch(module + "get_password_hash", return_value="test-hash"))
        self.addAsyncCleanup(self.cleanup_database)
        self.addCleanup(self.stack.close)

    async def cleanup_database(self):
        await self.transaction.rollback()
        await self.connection.close()
        await self.test_engine.dispose()

    def uow(self):
        return GenUnitOfWork(self.factory)

    async def create_employee(self, number="DETAILS-TEST", details=None):
        payload = {
            "employee_no": number, "first_name": "Test", "last_name": "Employee",
            "personal_email": f"{number.lower()}@example.com", "created_by": self.actor_id,
        }
        if details is not None:
            payload["personal_details"] = details
        return await CreateEmployeeUseCase(self.uow()).execute(payload)

    async def details(self, employee_id):
        response = await get_personal_details(employee_id, self.claims, self.uow())
        return response.data

    async def upload(self, rows, preview=False):
        return await import_personal_details(
            PersonalDetailsImportInput(rows=rows, preview=preview), self.claims, self.uow(),
        )

    async def test_create_and_update_save_separately_and_do_not_leak_into_employee_response(self):
        employee = await self.create_employee(details={"bank_account_no": "000123", "civil_status": "SINGLE"})
        self.assertNotIn("bank_account_no", asdict(employee))
        self.assertNotIn("personal_details", asdict(employee))
        self.assertEqual((await self.details(employee.id)).bank_account_no, "000123")
        payload = asdict(employee)
        payload["updated_by"] = self.actor_id
        payload["personal_details"] = {"civil_status": "MARRIED", "address_line_1": "Test street"}
        await UpdateEmployeeUseCase(self.uow()).execute(employee.id, payload)
        details = await self.details(employee.id)
        self.assertEqual(details.civil_status, "MARRIED")
        self.assertEqual(details.bank_account_no, "000123")
        self.assertEqual(details.address_line_1, "Test street")

    async def test_template_example_returns_earliest_saved_record_or_none(self):
        empty = await get_personal_details_template_example(self.claims, self.uow())
        self.assertIsNone(empty.data)
        first = await self.create_employee("EMP-OLDER", {"sss_no": "000123", "address_line_1": "Unit 1, Sample"})
        second = await self.create_employee("EMP-NEWER", {"sss_no": "000456"})
        async with self.factory() as session:
            await session.execute(
                text("UPDATE hr.employee_personal_details SET created_at = '2020-01-01' WHERE employee_id = :id"),
                {"id": first.id},
            )
            await session.execute(
                text("UPDATE hr.employee_personal_details SET created_at = '2021-01-01' WHERE employee_id = :id"),
                {"id": second.id},
            )
            await session.commit()
        response = await get_personal_details_template_example(self.claims, self.uow())
        self.assertEqual(response.data.employee_no, "EMP-OLDER")
        self.assertEqual(response.data.sss_no, "000123")
        self.assertEqual(response.data.address_line_1, "Unit 1, Sample")

    async def test_legacy_update_without_details_preserves_saved_information(self):
        employee = await self.create_employee(details={"sss_no": "000456"})
        payload = asdict(employee)
        payload["first_name"] = "Updated"
        await UpdateEmployeeUseCase(self.uow()).execute(employee.id, payload)
        self.assertEqual((await self.details(employee.id)).sss_no, "000456")

    async def test_legacy_address_and_psgc_selections_are_preserved(self):
        employee = await self.create_employee(details={
            "province": "Legacy province", "city_municipality": "Legacy city", "barangay": "Legacy barangay",
        })
        details = await self.details(employee.id)
        self.assertEqual(details.province, "Legacy province")
        self.assertIsNone(details.psgc_region_code)
        payload = asdict(employee)
        payload["personal_details"] = {
            "region": "Test region", "province": "Test province", "city_municipality": "Test city",
            "barangay": "Test barangay", "psgc_region_code": "010000000",
            "psgc_province_code": "010010000", "psgc_city_code": "010010100",
            "psgc_barangay_code": "010010101",
        }
        await UpdateEmployeeUseCase(self.uow()).execute(employee.id, payload)
        details = await self.details(employee.id)
        self.assertEqual(details.region, "Test region")
        self.assertEqual(details.psgc_barangay_code, "010010101")
        self.assertEqual(details.city_municipality, "Test city")

    async def test_import_rejects_psgc_codes_without_changing_details(self):
        employee = await self.create_employee(details={"province": "Saved"})
        with self.assertRaises(HTTPException) as error:
            await self.upload([{"employee_no": employee.employee_no, "psgc_province_code": "010010000"}])
        self.assertEqual(error.exception.status_code, 422)
        self.assertIsNone((await self.details(employee.id)).psgc_province_code)

    async def test_preview_is_read_only_and_apply_rechecks_conflicts_and_is_idempotent(self):
        employee = await self.create_employee(details={"sss_no": "000456"})
        rows = [{"employee_no": employee.employee_no, "sss_no": "OTHER", "tin_no": "000789", "province": "Test"}]
        preview = await self.upload(rows, preview=True)
        self.assertEqual(preview.data[0].conflicting_fields, ["sss_no"])
        self.assertIsNone((await self.details(employee.id)).tin_no)
        async with self.factory() as session:
            await save_personal_details(session, employee.id, EmployeePersonalDetailsInput(tin_no="NEWER"), self.actor_id)
            await session.commit()
        applied = await self.upload(rows)
        self.assertEqual(applied.data[0].filled_fields, ["province"])
        self.assertIn("tin_no", applied.data[0].conflicting_fields)
        self.assertEqual((await self.details(employee.id)).tin_no, "NEWER")
        self.assertEqual((await self.upload(rows)).data[0].status, "skipped")

    async def test_unknown_or_duplicate_employee_rejects_entire_file(self):
        employee = await self.create_employee()
        for rows in (
            [{"employee_no": employee.employee_no, "sss_no": "123"}, {"employee_no": "MISSING"}],
            [{"employee_no": employee.employee_no, "sss_no": "123"}] * 2,
        ):
            with self.assertRaises(HTTPException) as error:
                await self.upload(rows)
            self.assertEqual(error.exception.status_code, 422)
            self.assertIsNone(await self.details(employee.id))

    async def test_personal_details_failure_rolls_back_employee_creation(self):
        with patch(
            "app.filemaintenance.employees.application.use_case.save_personal_details",
            AsyncMock(side_effect=ValueError("Details could not be saved.")),
        ):
            with self.assertRaisesRegex(ValueError, "Details could not"):
                await self.create_employee(details={"tin_no": "001"})
        async with self.factory() as session:
            count = await session.scalar(select(func.count()).select_from(EmployeeModel))
            self.assertEqual(count, 0)

    async def test_explicit_form_clear_is_allowed_but_blank_import_never_clears(self):
        employee = await self.create_employee(details={"sss_no": "000456", "tin_no": "000789"})
        await self.upload([{"employee_no": employee.employee_no, "sss_no": "", "tin_no": None}])
        self.assertEqual((await self.details(employee.id)).sss_no, "000456")
        async with self.factory() as session:
            await save_personal_details(session, employee.id, EmployeePersonalDetailsInput(sss_no=None), self.actor_id)
            await session.commit()
        details = await self.details(employee.id)
        self.assertIsNone(details.sss_no)
        self.assertEqual(details.tin_no, "000789")

    async def test_concurrent_first_imports_fill_once_without_overwriting(self):
        factory = async_sessionmaker(self.test_engine, expire_on_commit=False)
        employee_id = uuid4()
        employee_no = f"CONCURRENT-{uuid4().hex[:12]}"
        async with factory() as session:
            session.add(EmployeeModel(
                id=employee_id, employee_no=employee_no, first_name="Test", last_name="Concurrent",
            ))
            await session.commit()
        try:
            async def upload(value):
                return await import_personal_details(
                    PersonalDetailsImportInput(
                        rows=[{"employee_no": employee_no, "bank_account_no": value}], preview=False,
                    ),
                    self.claims, GenUnitOfWork(factory),
                )

            first, second = await asyncio.gather(upload("000123"), upload("000456"))
            results = [first.data[0], second.data[0]]
            self.assertCountEqual([row.status for row in results], ["updated", "skipped"])
            self.assertEqual(sum(bool(row.conflicting_fields) for row in results), 1)
            winner = "000123" if results[0].status == "updated" else "000456"
            async with factory() as session:
                details = await session.get(EmployeePersonalDetailsModel, employee_id)
                self.assertEqual(details.bank_account_no, winner)
        finally:
            async with factory() as session:
                await session.execute(delete(EmployeeModel).where(EmployeeModel.id == employee_id))
                await session.commit()
