import json
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import init_db_models
from app.filemaintenance.employees.infrastructure import regularization_router as review


class RegularizationRulesTests(unittest.IsolatedAsyncioTestCase):
    def test_six_month_date_uses_calendar_months_and_clamps_month_end(self):
        self.assertEqual(review.six_month_date(date(2026, 1, 15)), date(2026, 7, 15))
        self.assertEqual(review.six_month_date(date(2025, 8, 31)), date(2026, 2, 28))
        self.assertEqual(review.six_month_date(date(2023, 8, 31)), date(2024, 2, 29))

    async def test_access_checks_current_role_not_token_claims(self):
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(role_codes=["SUPERVISOR"])))
        with self.assertRaises(HTTPException) as raised:
            await review.require_hr_admin({"sub": str(uuid4()), "role_codes": ["HR_ADMIN"]}, authorization)
        self.assertEqual(raised.exception.status_code, 403)
        authorization.execute.return_value = SimpleNamespace(role_codes=["HR_ADMIN"])
        user = uuid4()
        self.assertEqual(await review.require_hr_admin({"sub": str(user)}, authorization), user)


class RegularizationHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_enforce_current_hr_role_and_disable_caching(self):
        app = FastAPI()
        app.include_router(review.router, prefix="/employees")
        user = uuid4()
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(role_codes=["SUPERVISOR"])))

        class UnitOfWork:
            async def __aenter__(self):
                return SimpleNamespace(session=object())

            async def __aexit__(self, *args):
                return False

        app.dependency_overrides[review.get_current_user_claims] = lambda: {"sub": str(user), "role_codes": ["HR_ADMIN"]}
        app.dependency_overrides[review.get_current_authorization_use_case] = lambda: authorization
        app.dependency_overrides[review.get_unit_of_work] = UnitOfWork
        async def post(path, body=None):
            messages = []
            sent_request = False

            async def receive():
                nonlocal sent_request
                if sent_request:
                    return {"type": "http.disconnect"}
                sent_request = True
                return {"type": "http.request", "body": json.dumps(body or {}).encode(), "more_body": False}

            async def send(message):
                messages.append(message)

            await app({
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
                "query_string": b"", "headers": [(b"content-type", b"application/json")],
                "client": ("test", 1), "server": ("test", 80),
            }, receive, send)
            return messages[0], json.loads(messages[1]["body"])

        with patch.object(review, "load_candidates", new=AsyncMock(return_value=[])):
            response, _ = await post("/employees/regularization-review")
            self.assertEqual(response["status"], 403)
            response, _ = await post("/employees/regularization-review/dismiss", {"notification_date": "2026-06-15"})
            self.assertEqual(response["status"], 403)
            authorization.execute.return_value = SimpleNamespace(role_codes=["HR_ADMIN"])
            response, body = await post("/employees/regularization-review")
        self.assertEqual(response["status"], 200)
        self.assertEqual(dict(response["headers"])[b"cache-control"], b"no-store")
        self.assertEqual(body["data"]["candidates"], [])


class RegularizationDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        init_db_models()
        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.addAsyncCleanup(self.engine.dispose)
        self.connection = await self.engine.connect()
        self.addAsyncCleanup(self.connection.close)
        self.transaction = await self.connection.begin()
        self.addAsyncCleanup(self.transaction.rollback)
        for ddl in (
            "CREATE TEMP TABLE employees (id uuid, employee_no text, first_name text, middle_name text, last_name text, suffix text, preferred_name text, is_active boolean, record_status text)",
            "CREATE TEMP TABLE employment_assignments (id uuid, employee_id uuid, company_id uuid, org_unit_id uuid, employment_type text, hire_date date, effective_from date, effective_to date, separation_date date, status text, is_active boolean)",
            "CREATE TEMP TABLE companies (id uuid, legal_name text)",
            "CREATE TEMP TABLE org_units (id uuid, org_unit_name text)",
            "CREATE TEMP TABLE regularization_notifications (user_id uuid, notification_date date, created_at timestamptz NOT NULL DEFAULT now(), dismissed_at timestamptz, PRIMARY KEY (user_id, notification_date))",
        ):
            await self.connection.execute(text(ddl))
        await self.connection.execution_options(schema_translate_map={"hr": "pg_temp", "core": "pg_temp"})
        self.session = AsyncSession(bind=self.connection, expire_on_commit=False)
        self.addAsyncCleanup(self.session.close)
        self.company = uuid4()
        await self.session.execute(text("INSERT INTO companies VALUES (:id, 'Example Company')"), {"id": self.company})

    async def add_employee(self, code, hire_date, employment_type="PROBATIONARY", *, active=True, separation=None):
        employee, assignment = uuid4(), uuid4()
        await self.session.execute(text(
            "INSERT INTO employees VALUES (:id, :code, 'Test', NULL, 'Employee', NULL, NULL, :active, 'ACTIVE')"
        ), {"id": employee, "code": code, "active": active})
        await self.session.execute(text(
            "INSERT INTO employment_assignments VALUES "
            "(:id, :employee, :company, NULL, :type, :hire, :hire, NULL, :separation, 'ACTIVE', true)"
        ), {"id": assignment, "employee": employee, "company": self.company, "type": employment_type,
            "hire": hire_date, "separation": separation})
        return assignment

    async def test_candidate_threshold_overdue_regular_and_inactive_assignments(self):
        today = date(2026, 6, 15)
        threshold = await self.add_employee("THRESHOLD", date(2025, 12, 30))
        overdue = await self.add_employee("OVERDUE", date(2025, 10, 1))
        await self.add_employee("TOO-EARLY", date(2026, 1, 1))
        await self.add_employee("REGULAR", date(2025, 10, 1), " regular ")
        await self.add_employee("INACTIVE", date(2025, 10, 1), active=False)
        await self.add_employee("SEPARATED", date(2025, 10, 1), separation=date(2026, 6, 14))
        candidates = await review.load_candidates(self.session, today)
        self.assertEqual([item.assignment_id for item in candidates], [overdue, threshold])
        self.assertEqual([item.days_remaining for item in candidates], [-75, 15])
        await self.session.execute(text(
            "UPDATE employment_assignments SET employment_type='REGULAR' WHERE id=:id"
        ), {"id": threshold})
        self.assertEqual([item.assignment_id for item in await review.load_candidates(self.session, today)], [overdue])

    async def test_one_notification_per_user_day_and_none_without_candidates(self):
        await self.add_employee("CANDIDATE", date(2025, 1, 1))

        class UnitOfWork:
            async def __aenter__(inner):
                return SimpleNamespace(session=self.session)

            async def __aexit__(inner, *args):
                return False

        class FixedDateTime(datetime):
            current = datetime(2026, 6, 15, 12, 0)

            @classmethod
            def now(cls, tz=None):
                return cls.current.replace(tzinfo=tz)

        user, other = uuid4(), uuid4()
        with patch.object(review, "datetime", FixedDateTime):
            response = Response()
            first = await review.get_regularization_review(response, user, UnitOfWork())
            repeated = await review.get_regularization_review(Response(), user, UnitOfWork())
            self.assertTrue(first.data.notification_pending)
            self.assertTrue(repeated.data.notification_pending)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            await review.dismiss_regularization_notification(
                review.NotificationDismissal(notification_date=date(2026, 6, 15)), Response(), user, UnitOfWork()
            )
            after = await review.get_regularization_review(Response(), user, UnitOfWork())
            self.assertFalse(after.data.notification_pending)
            self.assertTrue((await review.get_regularization_review(Response(), other, UnitOfWork())).data.notification_pending)
            FixedDateTime.current = datetime(2026, 6, 16, 12, 0)
            self.assertTrue((await review.get_regularization_review(Response(), user, UnitOfWork())).data.notification_pending)
            await self.session.execute(text("UPDATE employment_assignments SET employment_type='REGULAR'"))
            empty = await review.get_regularization_review(Response(), uuid4(), UnitOfWork())
            self.assertEqual(empty.data.candidates, [])
            self.assertFalse(empty.data.notification_pending)
            total = await self.session.scalar(text("SELECT count(*) FROM regularization_notifications"))
            self.assertEqual(total, 3)


if __name__ == "__main__":
    unittest.main()
