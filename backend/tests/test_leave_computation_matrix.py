import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.auth.application.authorization import CurrentAuthorization
from app.auth.infrastructure.dependencies import get_current_authorization_use_case, get_current_user_claims
from app.audit.infrastructure.dependencies import get_audit_es_client
from app.core.generics.uow import get_unit_of_work
from app.core.database import AsyncSessionLocal, engine, init_db_models
from app.core.generics.uow import GenUnitOfWork
from app.auth.infrastructure.db_model import RoleModel, UserModel
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel, EmploymentAssignmentModel
from app.filemaintenance.roles.infrastructure.db_model import UserRoleModel
from app.filemaintenance.roles.infrastructure.permission_db_model import PermissionModel
from app.filemaintenance.roles.infrastructure.role_permission_db_model import RolePermissionModel
from app.filemaintenance.leaves.infrastructure.leave_matrix_router import (
    LeaveMatrixInput, LeaveMatrixModel, _authorized_companies, get_matrix, list_companies, router, save_matrix,
)


def setUpModule():
    init_db_models()


class FakeSession:
    def __init__(self):
        self.matrices = {}

    async def scalar(self, statement):
        return object()

    async def get(self, model, key):
        return self.matrices.get(key)

    def add(self, matrix):
        self.matrices[matrix.company_id] = matrix


class FakeUow:
    def __init__(self):
        self.session = FakeSession()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MatrixValidationTests(unittest.TestCase):
    def test_decimals_and_nonoverlapping_inclusive_ranges(self):
        value = LeaveMatrixInput(row_version=0, ranges=[
            {"worked_from": "4.00", "worked_to": "7.99", "leave_hours": "2.50"},
            {"worked_from": "0.00", "worked_to": "3.99", "leave_hours": "4.00"},
        ])
        self.assertEqual(value.ranges[0].model_dump(mode="json")["leave_hours"], "2.50")
        for ranges in [
            [{"worked_from": "4", "worked_to": "3", "leave_hours": "2"}],
            [{"worked_from": "0", "worked_to": "4", "leave_hours": "2"},
             {"worked_from": "4", "worked_to": "5", "leave_hours": "1"}],
            [{"worked_from": "0", "worked_to": "1.001", "leave_hours": "2"}],
            [{"worked_from": "0", "worked_to": "1", "leave_hours": "8.01"}],
        ]:
            with self.subTest(ranges=ranges), self.assertRaises(ValidationError):
                LeaveMatrixInput(row_version=0, ranges=ranges)


class MatrixHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_requires_leave_manage(self):
        actor_id = uuid4()
        authorization = SimpleNamespace(execute=AsyncMock(
            return_value=CurrentAuthorization([], [], None, None),
        ))
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides.update({
            get_current_user_claims: lambda: {"sub": str(actor_id), "email": "hr@example.invalid"},
            get_current_authorization_use_case: lambda: authorization,
            get_unit_of_work: FakeUow,
            get_audit_es_client: lambda: None,
        })
        async def request(method, body):
            messages = []
            delivered = False

            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}

            async def send(message):
                messages.append(message)

            path = f"/leave-computation-matrices/{uuid4()}"
            await app({
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                "query_string": b"", "headers": [(b"content-type", b"application/json")],
                "server": ("test", 80), "client": ("test", 1234), "root_path": "",
            }, receive, send)
            return next(message["status"] for message in messages if message["type"] == "http.response.start")

        self.assertEqual(await request("GET", b""), 403)
        self.assertEqual(await request("PUT", b'{"row_version":0,"ranges":[]}'), 403)


class MatrixStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_company_selection_requires_active_assignment_and_matching_permission(self):
        first, second = uuid4(), uuid4()
        claims = {"sub": str(uuid4()), "email": "hr@example.invalid"}
        uow = FakeUow()
        company = SimpleNamespace(id=second, company_code="B", legal_name="Company B")
        with patch("app.filemaintenance.leaves.infrastructure.leave_matrix_router.get_latest_active_employee_company_id",
                   new=AsyncMock(return_value=second)) as latest, \
             patch("app.filemaintenance.leaves.infrastructure.leave_matrix_router._authorized_companies",
                   new=AsyncMock(return_value=[company])):
            result = await list_companies(claims, uow)
            self.assertEqual([item.id for item in result.data], [second])
            latest.return_value = None
            with self.assertRaisesRegex(HTTPException, "No active employee company assignment"):
                await list_companies(claims, uow)
            latest.return_value = first
            with self.assertRaisesRegex(HTTPException, "do not have leave management access"):
                await list_companies(claims, uow)

    async def test_company_isolation_save_reload_and_concurrent_update(self):
        first, second = uuid4(), uuid4()
        uow = FakeUow()
        claims = {"sub": str(uuid4()), "email": "hr@example.invalid"}
        payload = LeaveMatrixInput(row_version=0, ranges=[
            {"worked_from": "4.00", "worked_to": "7.99", "leave_hours": "2.50"},
        ])
        with patch("app.filemaintenance.leaves.infrastructure.leave_matrix_router._authorized_companies",
                   new=AsyncMock(return_value=[SimpleNamespace(id=first), SimpleNamespace(id=second)])):
            saved = await save_matrix(first, payload, claims, uow, None)
            self.assertEqual(saved.data.row_version, 1)
            self.assertEqual((await get_matrix(first, claims, uow)).data.ranges[0].leave_hours, payload.ranges[0].leave_hours)
            self.assertEqual((await get_matrix(second, claims, uow)).data.ranges, [])
            with self.assertRaises(HTTPException) as error:
                await save_matrix(first, payload, claims, uow, None)
            self.assertEqual(error.exception.status_code, 409)
            updated = await save_matrix(first, LeaveMatrixInput(row_version=1, ranges=[]), claims, uow, None)
            self.assertEqual(updated.data.row_version, 2)
            self.assertEqual(updated.data.ranges, [])

    async def test_company_outside_scope_is_rejected(self):
        uow = FakeUow()
        claims = {"sub": str(uuid4()), "email": "hr@example.invalid"}
        with patch("app.filemaintenance.leaves.infrastructure.leave_matrix_router._authorized_companies",
                   new=AsyncMock(return_value=[])):
            for operation in (
                get_matrix(uuid4(), claims, uow),
                save_matrix(uuid4(), LeaveMatrixInput(row_version=0, ranges=[]), claims, uow, None),
            ):
                with self.assertRaises(HTTPException) as error:
                    await operation
                self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(uow.session.matrices, {})


@unittest.skipUnless(os.getenv("RUN_LEAVE_MATRIX_DATABASE_TESTS") == "1", "Requires disposable matrix-test database.")
class MatrixDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_company_permissions_and_persistence(self):
        url = make_url(os.environ["DATABASE_URL"])
        if url.host != "matrix-db" or url.database != "matrix_test":
            raise RuntimeError("Matrix database tests require the isolated matrix-db/matrix_test database.")
        init_db_models()
        models = [CompanyModel, UserModel, RoleModel, UserRoleModel, PermissionModel, RolePermissionModel,
                  EmployeeModel, EmploymentAssignmentModel, LeaveMatrixModel]
        actor, role, permission, assignment, first, second, employee, old_job, new_job = [uuid4() for _ in range(9)]
        async with engine.begin() as conn:
            for schema in ("core", "identity", "hr", "leave_mgmt"):
                await conn.execute(text(f"CREATE SCHEMA {schema}"))
            for model in models:
                table = model.__table__
                columns = ", ".join(
                    f'"{column.name}" {column.type.compile(dialect=conn.dialect)}'
                    + (" PRIMARY KEY" if column.name == "id" or model is LeaveMatrixModel and column.name == "company_id" else "")
                    for column in table.columns
                )
                await conn.execute(text(f'CREATE TABLE {table.schema}.{table.name} ({columns})'))
            for company, code in ((first, "A"), (second, "B")):
                await conn.execute(text("INSERT INTO core.companies (id, company_code, legal_name) VALUES (:id, :code, :code)"),
                                   {"id": company, "code": code})
            await conn.execute(text("INSERT INTO hr.employees (id, is_active, record_status) VALUES (:id, true, 'ACTIVE')"), {"id": employee})
            await conn.execute(text("INSERT INTO identity.users (id, employee_id, is_active, account_status) VALUES (:id, :employee, true, 'ACTIVE')"), {"id": actor, "employee": employee})
            await conn.execute(text("INSERT INTO identity.roles (id, is_active) VALUES (:id, true)"), {"id": role})
            await conn.execute(text("INSERT INTO identity.permissions (id, is_active, permission_code) VALUES (:id, true, 'leave.manage')"), {"id": permission})
            await conn.execute(text("INSERT INTO identity.role_permissions (role_id, permission_id, allowed) VALUES (:role, :permission, true)"), {"role": role, "permission": permission})
            await conn.execute(text("INSERT INTO identity.user_roles (id, user_id, role_id, company_id, effective_from) VALUES (:id, :actor, :role, :company, CURRENT_DATE)"),
                               {"id": assignment, "actor": actor, "role": role, "company": first})
            await conn.execute(text("INSERT INTO hr.employment_assignments (id, employee_id, company_id, effective_from, created_at, is_active, status) VALUES (:id, :employee, :company, CURRENT_DATE - 2, now(), true, 'ACTIVE')"),
                               {"id": old_job, "employee": employee, "company": first})
            await conn.execute(text("INSERT INTO hr.employment_assignments (id, employee_id, company_id, effective_from, created_at, is_active, status) VALUES (:id, :employee, :company, CURRENT_DATE - 1, now(), true, 'ACTIVE')"),
                               {"id": new_job, "employee": employee, "company": second})
        claims = {"sub": str(actor), "email": "hr@example.invalid"}
        uow = GenUnitOfWork(AsyncSessionLocal)
        async with AsyncSessionLocal() as session:
            self.assertEqual([company.id for company in await _authorized_companies(session, actor)], [first])
        with self.assertRaisesRegex(HTTPException, "do not have leave management access"):
            await list_companies(claims, uow)
        payload = LeaveMatrixInput(row_version=0, ranges=[
            {"worked_from": "0.00", "worked_to": "3.99", "leave_hours": "4.50"},
        ])
        self.assertEqual((await save_matrix(first, payload, claims, uow, None)).data.row_version, 1)
        self.assertEqual(str((await get_matrix(first, claims, uow)).data.ranges[0].leave_hours), "4.50")
        with self.assertRaises(HTTPException) as error:
            await get_matrix(second, claims, uow)
        self.assertEqual(error.exception.status_code, 403)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE identity.user_roles SET company_id = NULL WHERE id = :id"), {"id": assignment})
        async with AsyncSessionLocal() as session:
            self.assertEqual([company.id for company in await _authorized_companies(session, actor)], [first, second])
        self.assertEqual((await list_companies(claims, uow)).data[0].id, second)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE hr.employment_assignments SET effective_from = CURRENT_DATE - 1, created_at = '2020-01-01'"))
        expected = first if old_job.int > new_job.int else second
        self.assertEqual((await list_companies(claims, uow)).data[0].id, expected)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE hr.employment_assignments SET created_at = '2020-01-02' WHERE id = :id"), {"id": new_job})
        self.assertEqual((await list_companies(claims, uow)).data[0].id, second)
        for field, value in (
            ("effective_from", "CURRENT_DATE + 5"),
            ("effective_to", "CURRENT_DATE - 2"),
            ("separation_date", "CURRENT_DATE - 2"),
            ("status", "'INACTIVE'"),
            ("is_active", "false"),
        ):
            async with engine.begin() as conn:
                await conn.execute(text(f"UPDATE hr.employment_assignments SET {field} = {value} WHERE id = :id"), {"id": new_job})
            self.assertEqual((await list_companies(claims, uow)).data[0].id, first)
            async with engine.begin() as conn:
                await conn.execute(text("UPDATE hr.employment_assignments SET effective_from = CURRENT_DATE - 1, effective_to = NULL, separation_date = NULL, status = 'ACTIVE', is_active = true WHERE id = :id"), {"id": new_job})
        for table, field, inactive, active in (
            ("identity.users", "is_active", "false", "true"),
            ("identity.users", "account_status", "'DISABLED'", "'ACTIVE'"),
            ("hr.employees", "is_active", "false", "true"),
            ("hr.employees", "record_status", "'ARCHIVED'", "'ACTIVE'"),
        ):
            async with engine.begin() as conn:
                await conn.execute(text(f"UPDATE {table} SET {field} = {inactive}"))
            with self.assertRaisesRegex(HTTPException, "No active employee company assignment"):
                await list_companies(claims, uow)
            async with engine.begin() as conn:
                await conn.execute(text(f"UPDATE {table} SET {field} = {active}"))
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE hr.employment_assignments SET is_active = false WHERE id = :id"), {"id": new_job})
        self.assertEqual((await list_companies(claims, uow)).data[0].id, first)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE hr.employment_assignments SET is_active = false WHERE id = :id"), {"id": old_job})
        with self.assertRaisesRegex(HTTPException, "No active employee company assignment"):
            await list_companies(claims, uow)
        await engine.dispose()
