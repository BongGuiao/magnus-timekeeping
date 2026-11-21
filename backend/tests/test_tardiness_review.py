import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.attendance.infrastructure import tardiness_review_router
from app.attendance.infrastructure.tardiness_screening import TardinessReview, load_tardiness_review
from app.core.config import settings


class TardinessReviewAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_hr_role_is_required_even_if_token_claims_hr(self):
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(role_codes=["SUPERVISOR"])))
        with self.assertRaises(HTTPException) as raised:
            await tardiness_review_router.preview_previous_month_tardiness(
                Response(), {"sub": str(uuid4()), "role_codes": ["HR_ADMIN"]}, authorization, None,
            )
        self.assertEqual(raised.exception.status_code, 403)

    async def test_hr_preview_uses_previous_month_and_disables_caching(self):
        authorization = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(role_codes=["HR_ADMIN"])))
        session = object()

        class UnitOfWork:
            async def __aenter__(self):
                return SimpleNamespace(session=session)

            async def __aexit__(self, *args):
                return False

        start, end = date(2026, 11, 1), date(2026, 11, 30)
        review = TardinessReview(period_start=start, period_end=end, candidates=[])
        response = Response()
        with patch.object(tardiness_review_router, "previous_calendar_month", return_value=(start, end)), \
                patch.object(tardiness_review_router, "load_tardiness_review", new=AsyncMock(return_value=review)) as load:
            result = await tardiness_review_router.preview_previous_month_tardiness(
                response, {"sub": str(uuid4())}, authorization, UnitOfWork(),
            )
        load.assert_awaited_once_with(session, start, end)
        self.assertEqual(result.data, review)
        self.assertEqual(response.headers["Cache-Control"], "no-store")


class TardinessReviewDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        self.addAsyncCleanup(self.engine.dispose)
        self.connection = await self.engine.connect()
        self.addAsyncCleanup(self.connection.close)
        self.transaction = await self.connection.begin()
        self.addAsyncCleanup(self.transaction.rollback)
        for ddl in (
            "CREATE TEMP TABLE employees (id uuid, employee_no text, first_name text, middle_name text, last_name text, suffix text, preferred_name text)",
            "CREATE TEMP TABLE users (id uuid, employee_id uuid)",
            "CREATE TEMP TABLE attendance_records (id uuid, user_id uuid, work_date date, expected_clock_in_at timestamptz, clock_in_at timestamptz, corrected_clock_in_at timestamptz, late_minutes integer, record_status text)",
            "CREATE TEMP TABLE attendance_merge_sources (source_attendance_id uuid)",
            "CREATE TEMP TABLE employee_schedule_assignments (employee_id uuid, attendance_mode text, is_active boolean, status text, effective_from date, effective_to date, created_at timestamptz)",
            "CREATE TEMP TABLE correction_requests (employee_id uuid, work_date date, status text)",
        ):
            await self.connection.execute(text(ddl))
        await self.connection.execution_options(schema_translate_map={
            "hr": "pg_temp", "identity": "pg_temp", "attendance": "pg_temp", "schedule": "pg_temp",
        })
        self.session = AsyncSession(bind=self.connection)
        self.addAsyncCleanup(self.session.close)

    async def test_filters_real_records_and_preserves_correction_and_duplicate_warnings(self):
        employee, user = uuid4(), uuid4()
        await self.session.execute(text(
            "INSERT INTO employees (id, employee_no, first_name, last_name) VALUES (:id, 'TEST-001', 'Test', 'Employee')"
        ), {"id": employee})
        await self.session.execute(text("INSERT INTO users VALUES (:id, :employee)"), {"id": user, "employee": employee})
        expected = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
        corrected = datetime(2026, 11, 2, 1, 15, tzinfo=timezone.utc)
        records = []
        for day in range(1, 8):
            records.append({
                "id": uuid4(), "user": user, "work_date": date(2026, 11, day),
                "expected": expected.replace(day=day), "clock": expected.replace(day=day),
                "corrected": corrected if day == 2 else None,
                "late": 15, "status": "INVALID" if day == 7 else "VALID",
            })
        records.append({**records[0], "id": uuid4()})
        records.append({**records[0], "id": uuid4(), "work_date": date(2026, 10, 31)})
        await self.session.execute(text(
            "INSERT INTO attendance_records VALUES (:id, :user, :work_date, :expected, :clock, :corrected, :late, :status)"
        ), records)
        await self.session.execute(text(
            "INSERT INTO attendance_merge_sources VALUES (:id)"
        ), {"id": records[5]["id"]})
        await self.session.execute(text(
            "INSERT INTO employee_schedule_assignments VALUES (:employee, 'SCHEDULE_CREDITED', true, 'ACTIVE', "
            "'2026-11-05', '2026-11-05', now())"
        ), {"employee": employee})
        await self.session.execute(text(
            "INSERT INTO correction_requests VALUES (:employee, '2026-11-02', 'PENDING'), "
            "(:employee, '2026-11-03', 'APPROVED')"
        ), {"employee": employee})

        review = await load_tardiness_review(self.session, date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual(len(review.candidates), 1)
        candidate = review.candidates[0]
        self.assertEqual(candidate.employee_no, "TEST-001")
        self.assertEqual(candidate.late_dates, tuple(date(2026, 11, day) for day in (1, 2, 3, 4)))
        self.assertEqual(candidate.duplicate_dates, (date(2026, 11, 1),))
        self.assertEqual(candidate.pending_correction_dates, (date(2026, 11, 2),))
        self.assertEqual(len(candidate.records), 6)
        self.assertEqual(next(row for row in candidate.records if row.work_date.day == 2).clock_in_at, corrected)
        self.assertEqual(next(row for row in candidate.records if row.work_date.day == 5).late_minutes, 0)


if __name__ == "__main__":
    unittest.main()
