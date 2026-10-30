import asyncio
import os
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.attendance.application.use_case import (
    ClockAttendanceInputDTO,
    ClockAttendanceUseCase,
    RecordBreakInputDTO,
    RecordBreakUseCase,
    lock_attendance_user,
)
from app.attendance.infrastructure.db_model import AttendanceModel
from app.auth.infrastructure.db_model import UserModel
from app.core.database import init_db_models
from app.core.face_recognition_service import find_best_match
from app.core.generics.uow import GenUnitOfWork
from app.enrollment.domain.entities.enrollment import EnrollmentStatus
from app.enrollment.infrastructure.db_model import FaceEnrollmentModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel


class AttendanceConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_face_extraction_runs_off_loop_with_bounded_concurrency(self):
        main_thread = threading.get_ident()
        active = 0
        peak = 0
        extraction_threads = []
        guard = threading.Lock()

        def extract(image):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
                extraction_threads.append(threading.get_ident())
            try:
                time.sleep(0.02)
                return [0.0] * 128
            finally:
                with guard:
                    active -= 1

        uow = AsyncMock(__aenter__=AsyncMock(side_effect=ValueError("stop after extraction")))
        face = SimpleNamespace(extract_face_encoding=extract)
        calls = [
            ClockAttendanceUseCase(uow, face)._execute(
                ClockAttendanceInputDTO(image_bytes=b"synthetic", user_id=uuid4()),
            ),
            RecordBreakUseCase(uow, face)._execute(
                RecordBreakInputDTO(
                    image_bytes=b"synthetic", user_id=uuid4(), break_type="first_break_out_at",
                ),
            ),
        ]
        results = await asyncio.gather(*calls, return_exceptions=True)
        self.assertTrue(all(isinstance(result, ValueError) for result in results))
        self.assertEqual(len(extraction_threads), 2)
        self.assertNotIn(main_thread, extraction_threads)
        self.assertEqual(peak, 1)

    async def test_account_lock_uses_for_update_and_refreshes_account_state(self):
        employee_id = uuid4()
        session = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(
            employee_id=employee_id, is_active=True, account_status="ACTIVE",
        )))
        await lock_attendance_user(session, uuid4(), employee_id)
        statement = session.scalar.await_args.args[0]
        self.assertIn("FOR UPDATE", str(statement.compile(dialect=postgresql.dialect())))
        self.assertTrue(statement.get_execution_options()["populate_existing"])
        session.scalar.return_value.is_active = False
        with self.assertRaisesRegex(ValueError, "inactive"):
            await lock_attendance_user(session, uuid4(), employee_id)

    async def test_commit_failure_still_closes_session_and_propagates_error(self):
        session = SimpleNamespace(
            commit=AsyncMock(side_effect=RuntimeError("commit failed")),
            rollback=AsyncMock(),
            close=AsyncMock(),
        )
        uow = GenUnitOfWork(Mock(return_value=session))
        with self.assertRaisesRegex(RuntimeError, "commit failed"):
            async with uow:
                pass
        session.close.assert_awaited_once()

    async def test_rollback_failure_still_closes_session(self):
        session = SimpleNamespace(
            commit=AsyncMock(),
            rollback=AsyncMock(side_effect=RuntimeError("rollback failed")),
            close=AsyncMock(),
        )
        uow = GenUnitOfWork(Mock(return_value=session))
        with self.assertRaisesRegex(RuntimeError, "rollback failed"):
            async with uow:
                raise ValueError("punch failed")
        session.close.assert_awaited_once()


TEST_DATABASE_URL = os.getenv("ATTENDANCE_LOAD_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "Requires a migrated, disposable attendance load-test database.")
class AttendanceDatabaseConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if TEST_DATABASE_URL is None:
            self.skipTest("Requires a disposable attendance load-test database.")
        url = make_url(TEST_DATABASE_URL)
        if not (url.database or "").startswith("attendance_load_test_"):
            raise RuntimeError("Load tests require a disposable attendance_load_test_* database.")
        init_db_models()
        self.engine = create_async_engine(url)
        self.addAsyncCleanup(self.engine.dispose)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.employee_ids = [uuid4() for _ in range(100)]
        self.user_ids = [uuid4() for _ in range(100)]
        self.addAsyncCleanup(self.remove_fixtures)
        prefix = f"LOAD-{uuid4().hex[:8]}"
        async with self.factory.begin() as session:
            session.add_all([
                EmployeeModel(
                    id=employee_id, employee_no=f"{prefix}-{index}",
                    first_name="Synthetic", last_name="Load Test",
                )
                for index, employee_id in enumerate(self.employee_ids)
            ])
            await session.flush()
            session.add_all([
                UserModel(
                    id=user_id, employee_id=self.employee_ids[index],
                    username=f"{prefix}-{index}", password_hash="not-a-login-credential",
                    account_status="ACTIVE",
                )
                for index, user_id in enumerate(self.user_ids)
            ])
            session.add_all([
                FaceEnrollmentModel(
                    employee_id=employee_id, face_encoding=[float(index)] + [0.0] * 127,
                    status=EnrollmentStatus.ENROLLED,
                )
                for index, employee_id in enumerate(self.employee_ids)
            ])
        self.face = SimpleNamespace(
            extract_face_encoding=lambda image: [float(image.decode())] + [0.0] * 127,
            find_best_match=lambda candidate, known: find_best_match(candidate, known, threshold=0.5),
        )

    async def remove_fixtures(self):
        async with self.factory.begin() as session:
            await session.execute(delete(AttendanceModel).where(AttendanceModel.user_id.in_(self.user_ids)))
            await session.execute(delete(UserModel).where(UserModel.id.in_(self.user_ids)))
            await session.execute(delete(FaceEnrollmentModel).where(
                FaceEnrollmentModel.employee_id.in_(self.employee_ids),
            ))
            await session.execute(delete(EmployeeModel).where(EmployeeModel.id.in_(self.employee_ids)))

    async def punch(self, index):
        use_case = ClockAttendanceUseCase(GenUnitOfWork(self.factory), self.face)
        return await use_case._execute(ClockAttendanceInputDTO(
            image_bytes=str(index).encode(), user_id=self.user_ids[index],
            clock_out_confirmed=True, clock_channel={"synthetic_load_test": True},
        ))

    async def test_100_simultaneous_mixed_clock_in_and_out(self):
        now = datetime.now(timezone.utc)
        async with self.factory.begin() as session:
            session.add_all([
                AttendanceModel(
                    user_id=user_id, work_date=now.astimezone(ZoneInfo("Asia/Manila")).date(),
                    clock_in_at=now - timedelta(minutes=6),
                )
                for user_id in self.user_ids[50:]
            ])

        latencies = []

        async def timed_punch(index):
            started = time.perf_counter()
            result = await self.punch(index)
            latencies.append(time.perf_counter() - started)
            return result

        started = time.perf_counter()
        results = await asyncio.wait_for(
            asyncio.gather(*(timed_punch(index) for index in range(100))),
            timeout=60,
        )
        elapsed = time.perf_counter() - started
        self.assertEqual([result.action for result in results[:50]], ["clock_in"] * 50)
        self.assertEqual([result.action for result in results[50:]], ["clock_out"] * 50)
        async with self.factory() as session:
            records = list(await session.scalars(
                select(AttendanceModel).where(AttendanceModel.user_id.in_(self.user_ids)),
            ))
        self.assertEqual(len(records), 100)
        self.assertEqual(len({record.user_id for record in records}), 100)
        self.assertEqual(sum(record.clock_out_at is None for record in records), 50)
        print(
            f"\n100 mixed punches: total={elapsed:.3f}s, "
            f"p95={sorted(latencies)[94]:.3f}s, max={max(latencies):.3f}s; "
            "100 persisted, 50 in / 50 out."
        )

    async def test_overlapping_clock_ins_create_only_one_record(self):
        async with self.factory.begin() as session:
            await session.execute(text("""
                CREATE FUNCTION attendance.load_test_delay() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.2); RETURN NEW; END $$;
            """))
            await session.execute(text("""
                CREATE TRIGGER load_test_delay BEFORE INSERT ON attendance.attendance_records
                FOR EACH ROW EXECUTE FUNCTION attendance.load_test_delay();
            """))
        try:
            results = await asyncio.wait_for(
                asyncio.gather(self.punch(0), self.punch(0), return_exceptions=True), timeout=10,
            )
            successes = [result for result in results if not isinstance(result, BaseException)]
            errors = [result for result in results if isinstance(result, BaseException)]
            self.assertEqual(len(successes), 1)
            self.assertEqual(successes[0].action, "clock_in")
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ValueError)
            async with self.factory() as session:
                count = await session.scalar(select(func.count()).select_from(AttendanceModel).where(
                    AttendanceModel.user_id == self.user_ids[0],
                ))
            self.assertEqual(count, 1)
        finally:
            async with self.factory.begin() as session:
                await session.execute(text(
                    "DROP TRIGGER load_test_delay ON attendance.attendance_records",
                ))
                await session.execute(text("DROP FUNCTION attendance.load_test_delay()"))

    async def test_overlapping_clock_outs_do_not_start_a_new_shift(self):
        now = datetime.now(timezone.utc)
        async with self.factory.begin() as session:
            session.add(AttendanceModel(
                user_id=self.user_ids[0], work_date=now.astimezone(ZoneInfo("Asia/Manila")).date(),
                clock_in_at=now - timedelta(minutes=6),
            ))
        results = await asyncio.wait_for(
            asyncio.gather(self.punch(0), self.punch(0), return_exceptions=True), timeout=10,
        )
        successes = [result for result in results if not isinstance(result, BaseException)]
        self.assertEqual([result.action for result in successes], ["clock_out"])
        async with self.factory() as session:
            records = list(await session.scalars(
                select(AttendanceModel).where(AttendanceModel.user_id == self.user_ids[0]),
            ))
        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0].clock_out_at)

    async def test_new_request_after_clock_out_can_start_another_shift(self):
        now = datetime.now(timezone.utc)
        async with self.factory.begin() as session:
            session.add(AttendanceModel(
                user_id=self.user_ids[0], work_date=now.astimezone(ZoneInfo("Asia/Manila")).date(),
                clock_in_at=now - timedelta(minutes=6),
            ))
        self.assertEqual((await self.punch(0)).action, "clock_out")
        self.assertEqual((await self.punch(0)).action, "clock_in")

    async def test_break_and_clock_out_cannot_overwrite_each_other(self):
        now = datetime.now(timezone.utc)
        async with self.factory.begin() as session:
            session.add(AttendanceModel(
                user_id=self.user_ids[0], work_date=now.astimezone(ZoneInfo("Asia/Manila")).date(),
                clock_in_at=now - timedelta(minutes=6),
            ))
        break_case = RecordBreakUseCase(GenUnitOfWork(self.factory), self.face)
        results = await asyncio.wait_for(asyncio.gather(
            self.punch(0),
            break_case._execute(RecordBreakInputDTO(
                image_bytes=b"0", user_id=self.user_ids[0], break_type="first_break_out_at",
            )),
            return_exceptions=True,
        ), timeout=10)
        self.assertEqual(sum(not isinstance(result, BaseException) for result in results), 1)
        errors = [result for result in results if isinstance(result, BaseException)]
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)
        async with self.factory() as session:
            record = await session.scalar(
                select(AttendanceModel).where(AttendanceModel.user_id == self.user_ids[0]),
            )
        self.assertNotEqual(record.clock_out_at is None, record.first_break_out_at is None)


if __name__ == "__main__":
    unittest.main()
