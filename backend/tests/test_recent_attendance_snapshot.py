import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.attendance.infrastructure import router
from app.tasks import dashboard_tasks


class RecentAttendanceSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_and_employee_snapshot_use_identical_corrected_net_minutes(self) -> None:
        employee_id = uuid4()
        user_id = uuid4()
        start = datetime(2026, 10, 12, tzinfo=timezone.utc)
        row = SimpleNamespace(
            employee_id=employee_id, employee_code="EMP001", employee_name="Employee",
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
        engine = MagicMock()
        session = MagicMock()
        ranked_rows = MagicMock()
        ranked_rows.all.return_value = [row]
        applications = MagicMock()
        applications.scalars.return_value = []
        session.execute.side_effect = [[row], ranked_rows, applications, []]
        with (
            patch.object(dashboard_tasks, "create_engine", return_value=engine),
            patch.object(dashboard_tasks, "Session") as session_factory,
        ):
            session_factory.return_value.__enter__.return_value = session
            snapshots = dashboard_tasks.load_recent_attendance_snapshots(str(user_id))
        snapshot = snapshots[str(user_id)]
        self.assertEqual(snapshot["weekly_minutes_worked"], 481)
        self.assertEqual(snapshot["records"][0]["minutes_worked"], 481)

        empty_result = MagicMock()
        empty_result.all.return_value = []
        weekly_result = MagicMock()
        weekly_result.all.return_value = [row]
        uow = MagicMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)
        uow.session.execute = AsyncMock(side_effect=[empty_result, empty_result, weekly_result])
        response = await router.get_admin_dashboard_snapshot(
            claims={"role": "admin", "employee_id": str(employee_id)}, uow=uow,
        )
        self.assertEqual(response.data.weekly_hours[0].minutes_worked, 481)
        self.assertEqual(
            response.data.weekly_hours[0].hours_worked, snapshot["weekly_hours_worked"],
        )

    async def test_force_refresh_returns_live_checkout_instead_of_cached_snapshot(self) -> None:
        user_id = uuid4()
        timestamp = "2026-10-09T19:55:00+08:00"
        live_snapshot = {
            "records": [
                {
                    "date": "2026-10-09",
                    "time_in": "2026-10-09T09:00:00+08:00",
                    "time_out": timestamp,
                    "minutes_worked": 480,
                    "status": "present",
                }
            ],
            "weekly_hours_worked": 8,
            "weekly_minutes_worked": 480,
            "missed_clock_ins_this_month": 0,
            "refreshed_at": timestamp,
        }
        cache = type(
            "AsyncCache",
            (),
            {
                "set": AsyncMock(),
                "mget": AsyncMock(return_value=("stale-snapshot", timestamp)),
                "aclose": AsyncMock(),
            },
        )()

        with (
            patch.object(router.Redis, "from_url", return_value=cache),
            patch.object(
                router,
                "load_recent_attendance_snapshots",
                return_value={str(user_id): live_snapshot},
            ) as load_snapshots,
        ):
            response = await router.get_recent_attendance_snapshot(
                force_refresh=True,
                claims={"sub": str(user_id)},
            )

        self.assertEqual(response.data.records[0].time_out, timestamp)
        self.assertEqual(response.data.records[0].minutes_worked, 480)
        self.assertEqual(response.data.weekly_minutes_worked, 480)
        load_snapshots.assert_called_once_with(str(user_id))
        cache.mget.assert_not_awaited()
        cache.set.assert_awaited()
        cached_snapshot = json.loads(cache.set.await_args_list[0].args[1])
        self.assertEqual(cached_snapshot["records"][0]["time_out"], timestamp)
        cache.aclose.assert_awaited_once()
