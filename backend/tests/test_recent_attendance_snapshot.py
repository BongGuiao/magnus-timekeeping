import json
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.attendance.application.recent_attendance_ports import SnapshotStoreError
from app.attendance.application.recent_attendance_snapshot import RecentAttendanceSnapshot
from app.attendance.application.recent_attendance_use_cases import (
    GetRecentAttendanceSnapshotInput,
    GetRecentAttendanceSnapshotUseCase,
)
from app.attendance.domain.exceptions import SnapshotUnavailableError
from app.attendance.infrastructure import recent_attendance_adapters
from app.attendance.infrastructure.attendance_dashboard_router import get_recent_attendance_snapshot
from app.attendance.infrastructure.recent_attendance_adapters import (
    RedisRecentAttendanceSnapshotCache,
    TaskRecentAttendanceSnapshotLoader,
)
from app.tasks import dashboard_tasks

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
TIMESTAMP = "2026-10-09T19:55:00+08:00"


def live_snapshot(minutes=480):
    return {
        "records": [{
            "date": "2026-10-09", "time_in": "2026-10-09T09:00:00+08:00",
            "time_out": TIMESTAMP, "minutes_worked": minutes, "status": "present",
        }],
        "weekly_hours_worked": minutes / 60,
        "weekly_minutes_worked": minutes,
        "missed_clock_ins_this_month": 0,
        "refreshed_at": TIMESTAMP,
    }


class FakeLoader:
    def __init__(self, snapshot):
        self.snapshot, self.calls = snapshot, []

    async def load(self, user_id):
        self.calls.append(user_id)
        return self.snapshot


class FakeCache:
    def __init__(self, serialized=None, refreshed_at=None, read_error=None, write_error=None):
        self.serialized, self.refreshed_at = serialized, refreshed_at
        self.read_error, self.write_error = read_error, write_error
        self.written, self.reads = [], 0

    async def read(self, user_id):
        self.reads += 1
        if self.read_error:
            raise self.read_error
        return self.serialized, self.refreshed_at

    async def write(self, user_id, snapshot):
        if self.write_error:
            raise self.write_error
        self.written.append((user_id, snapshot))


class EmployeeSnapshotTaskTests(unittest.TestCase):
    def test_employee_snapshot_uses_corrected_punches_and_net_minutes(self):
        user_id = uuid4()
        start = datetime(2026, 10, 12, tzinfo=timezone.utc)
        row = SimpleNamespace(
            employee_id=uuid4(), employee_code="EMP001", employee_name="Employee",
            user_id=user_id, attendance_id=uuid4(), schedule_template_id=None,
            work_date=start.date(), corrected_clock_in_at=start,
            clock_in_at=start - timedelta(hours=1),
            corrected_clock_out_at=start + timedelta(hours=9, minutes=1),
            clock_out_at=start + timedelta(hours=10),
            expected_clock_in_at=start, expected_clock_out_at=start + timedelta(hours=9),
            is_absent=False, leave_type=None, overtime_request_status=None,
            punch_metadata={"break_calculation": {"net_nonpayable_minutes": 60}},
            **dict.fromkeys([
                "late_minutes", "undertime_minutes", "calculated_ot_minutes", "overtime_hours",
                "regular_overtime_minutes", "regular_overtime_hours",
                "night_differential_overtime_minutes", "night_differential_overtime_hours",
                "night_differential_minutes", "night_differential_hours",
                "requested_regular_overtime_minutes", "requested_night_differential_overtime_minutes",
                "requested_night_differential_minutes", "approved_regular_overtime_minutes",
                "approved_night_differential_overtime_minutes", "approved_night_differential_minutes",
            ], 0),
        )
        session = MagicMock()
        ranked_rows = MagicMock()
        ranked_rows.all.return_value = [row]
        applications = MagicMock()
        applications.scalars.return_value = []
        session.execute.side_effect = [[row], ranked_rows, applications, []]
        with (
            patch.object(dashboard_tasks, "create_engine", return_value=MagicMock()),
            patch.object(dashboard_tasks, "Session") as session_factory,
        ):
            session_factory.return_value.__enter__.return_value = session
            snapshot = dashboard_tasks.load_recent_attendance_snapshots(str(user_id))[str(user_id)]
        self.assertEqual(snapshot["weekly_minutes_worked"], 481)
        self.assertEqual(snapshot["records"][0]["minutes_worked"], 481)


class GetRecentAttendanceSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id = uuid4()

    def use_case(self, loader=None, cache=None):
        return GetRecentAttendanceSnapshotUseCase(
            loader or FakeLoader(live_snapshot()), cache or FakeCache(), clock=lambda: NOW,
        )

    async def run_use_case(self, use_case, force_refresh):
        return await use_case.execute(GetRecentAttendanceSnapshotInput(self.user_id, force_refresh))

    async def test_force_refresh_returns_live_data_and_replaces_the_cached_copy(self):
        loader, cache = FakeLoader(live_snapshot()), FakeCache(serialized="stale-snapshot")
        snapshot = await self.run_use_case(self.use_case(loader, cache), True)

        self.assertEqual(snapshot.records[0].time_out, TIMESTAMP)
        self.assertEqual((snapshot.records[0].minutes_worked, snapshot.weekly_minutes_worked), (480, 480))
        self.assertEqual(loader.calls, [self.user_id])
        self.assertEqual(cache.reads, 0)
        self.assertEqual(cache.written, [(self.user_id, snapshot)])

    async def test_force_refresh_without_live_data_returns_an_empty_snapshot_stamped_now(self):
        snapshot = await self.run_use_case(self.use_case(FakeLoader(None)), True)
        self.assertEqual(snapshot.records, [])
        self.assertEqual((snapshot.weekly_minutes_worked, snapshot.refreshed_at), (0, NOW.isoformat()))

    async def test_failed_cache_update_does_not_fail_a_forced_refresh(self):
        cache = FakeCache(write_error=SnapshotStoreError("redis down"))
        with self.assertLogs("app.attendance.application.recent_attendance_use_cases", "ERROR"):
            snapshot = await self.run_use_case(self.use_case(cache=cache), True)
        self.assertEqual(snapshot.weekly_minutes_worked, 480)

    async def test_cached_snapshot_is_served_without_loading_live_data(self):
        cached = RecentAttendanceSnapshot.model_validate(live_snapshot(300))
        loader, cache = FakeLoader(live_snapshot()), FakeCache(serialized=cached.model_dump_json())
        snapshot = await self.run_use_case(self.use_case(loader, cache), False)
        self.assertEqual(snapshot.weekly_minutes_worked, 300)
        self.assertEqual(loader.calls, [])

    async def test_missing_user_entry_with_a_global_marker_means_nothing_to_show(self):
        snapshot = await self.run_use_case(self.use_case(cache=FakeCache(refreshed_at=TIMESTAMP)), False)
        self.assertEqual((snapshot.records, snapshot.refreshed_at), ([], TIMESTAMP))

    async def test_unavailable_snapshots_are_reported_with_specific_messages(self):
        cases = (
            (FakeCache(), "has not been generated yet"),
            (FakeCache(serialized="{not json"), "is invalid"),
            (FakeCache(serialized=json.dumps({"records": "nope"})), "is invalid"),
            (FakeCache(read_error=SnapshotStoreError("down")), "temporarily unavailable"),
        )
        for cache, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(SnapshotUnavailableError, message):
                await self.run_use_case(self.use_case(cache=cache), False)


class RedisSnapshotCacheTests(unittest.IsolatedAsyncioTestCase):
    def redis(self, **methods):
        return type("AsyncCache", (), {"set": AsyncMock(), "mget": AsyncMock(), "aclose": AsyncMock(), **methods})()

    async def test_write_stores_snapshot_and_global_marker_with_ttl_then_closes(self):
        user_id, cache = uuid4(), self.redis()
        snapshot = RecentAttendanceSnapshot.model_validate(live_snapshot())
        with patch.object(recent_attendance_adapters.Redis, "from_url", return_value=cache):
            await RedisRecentAttendanceSnapshotCache().write(user_id, snapshot)

        first, second = cache.set.await_args_list
        self.assertTrue(first.args[0].endswith(f":{user_id}"))
        self.assertEqual(json.loads(first.args[1])["records"][0]["time_out"], TIMESTAMP)
        self.assertEqual(second.args[1], TIMESTAMP)
        self.assertEqual(first.kwargs["ex"], recent_attendance_adapters.settings.DASHBOARD_CACHE_TTL)
        cache.aclose.assert_awaited_once()

    async def test_redis_errors_become_store_errors_and_the_connection_is_still_closed(self):
        cache = self.redis(set=AsyncMock(side_effect=RedisError("boom")), mget=AsyncMock(side_effect=RedisError("boom")))
        snapshot = RecentAttendanceSnapshot.model_validate(live_snapshot())
        adapter = RedisRecentAttendanceSnapshotCache()
        with patch.object(recent_attendance_adapters.Redis, "from_url", return_value=cache):
            with self.assertRaises(SnapshotStoreError):
                await adapter.write(uuid4(), snapshot)
            with self.assertRaises(SnapshotStoreError):
                await adapter.read(uuid4())
        self.assertEqual(cache.aclose.await_count, 2)

    async def test_read_returns_snapshot_and_marker(self):
        cache = self.redis(mget=AsyncMock(return_value=("data", TIMESTAMP)))
        with patch.object(recent_attendance_adapters.Redis, "from_url", return_value=cache):
            self.assertEqual(await RedisRecentAttendanceSnapshotCache().read(uuid4()), ("data", TIMESTAMP))

    async def test_loader_returns_only_the_requested_users_snapshot(self):
        user_id = uuid4()
        with patch.object(
            recent_attendance_adapters, "load_recent_attendance_snapshots",
            return_value={str(user_id): live_snapshot()},
        ) as load:
            self.assertEqual(await TaskRecentAttendanceSnapshotLoader().load(user_id), live_snapshot())
            load.assert_called_once_with(str(user_id))
        with patch.object(recent_attendance_adapters, "load_recent_attendance_snapshots", return_value={}):
            self.assertIsNone(await TaskRecentAttendanceSnapshotLoader().load(user_id))


class RecentSnapshotRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_snapshot_is_a_503_with_the_use_case_message(self):
        use_case = MagicMock(execute=AsyncMock(side_effect=SnapshotUnavailableError("not ready")))
        with self.assertRaises(HTTPException) as error:
            await get_recent_attendance_snapshot(force_refresh=False, claims={"sub": str(uuid4())}, use_case=use_case)
        self.assertEqual((error.exception.status_code, error.exception.detail), (503, "not ready"))

    async def test_force_refresh_flag_and_user_are_passed_to_the_use_case(self):
        user_id = uuid4()
        use_case = MagicMock(execute=AsyncMock(return_value=RecentAttendanceSnapshot.model_validate(live_snapshot())))
        response = await get_recent_attendance_snapshot(force_refresh=True, claims={"sub": str(user_id)}, use_case=use_case)
        data = use_case.execute.await_args.args[0]
        self.assertEqual((data.user_id, data.force_refresh), (user_id, True))
        self.assertEqual(response.data.records[0].time_out, TIMESTAMP)

    async def test_missing_user_claim_is_unauthorized(self):
        with self.assertRaises(HTTPException) as error:
            await get_recent_attendance_snapshot(force_refresh=False, claims={}, use_case=MagicMock())
        self.assertEqual(error.exception.status_code, 401)
