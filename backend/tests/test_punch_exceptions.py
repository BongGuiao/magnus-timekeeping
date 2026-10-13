import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.attendance.infrastructure.clock_policy import AttendanceClockPolicy
from app.attendance.infrastructure.db_model import PunchExceptionModel
from app.attendance.infrastructure.punch_exceptions import (
    PunchRuleViolation,
    build_punch_metadata,
    log_rejected_punches,
    record_rejected_punch,
)
from app.attendance.infrastructure.router import router
from app.core.database import init_db_models


class PunchMetadataTests(unittest.TestCase):
    def test_reported_location_and_source_are_preserved_without_sensitive_data(self):
        timestamp = datetime(2026, 10, 12, tzinfo=timezone.utc)
        metadata = build_punch_metadata(
            14.5, 121.0, 8.5,
            AttendanceClockPolicy("mobile", True, "127.0.0.1", is_native=True),
            timestamp,
        )
        self.assertEqual(metadata["location_report"], {
            "status": "REPORTED", "latitude": 14.5, "longitude": 121.0,
            "accuracy_meters": 8.5, "received_at": timestamp.isoformat(),
            "source": "CLIENT_GPS", "verified": False,
        })
        self.assertEqual(metadata["client_source"], "native")
        self.assertEqual(set(metadata), {"location_report", "clock_policy", "client_source"})

    def test_kiosk_without_coordinates_is_explicitly_unavailable(self):
        policy = AttendanceClockPolicy("kiosk", False, "127.0.0.1")
        metadata = build_punch_metadata(None, None, None, policy, datetime.now(timezone.utc))
        self.assertEqual(metadata["location_report"]["status"], "UNAVAILABLE")
        self.assertEqual(metadata["clock_policy"]["channel"], "kiosk")
        self.assertFalse(policy.geofence_required)

    def test_partial_coordinates_are_not_reported_as_complete_location(self):
        metadata = build_punch_metadata(
            14.5, None, 8.5, AttendanceClockPolicy("desktop", False, None),
            datetime.now(timezone.utc),
        )
        self.assertEqual(metadata["location_report"]["status"], "UNAVAILABLE")

    def test_exception_model_metadata_is_jsonb(self):
        self.assertEqual(PunchExceptionModel.__table__.schema, "attendance")
        self.assertEqual(str(PunchExceptionModel.__table__.c.punch_metadata.type), "JSONB")

    def test_decorator_preserves_clock_and_break_api_signatures(self):
        app = FastAPI()
        app.include_router(router)
        schema = app.openapi()
        for path in ("/attendance/clock", "/attendance/clock-break"):
            reference = schema["paths"][path]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
            fields = schema["components"]["schemas"][reference.rsplit("/", 1)[1]]["properties"]
            self.assertIn("latitude", fields)
            self.assertIn("longitude", fields)
            self.assertIn("gps_accuracy_meters", fields)
            self.assertNotIn("args", fields)
            self.assertNotIn("kwargs", fields)


class RejectedPunchLoggingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        init_db_models()
        self.user_id = uuid4()
        self.policy = AttendanceClockPolicy("mobile", True, "127.0.0.1", is_native=True)

    async def test_validation_failure_is_recorded_then_original_error_reraised(self):
        error = PunchRuleViolation("Too early", "CLOCK_IN_TOO_EARLY", {"allowance_minutes": 30})

        @log_rejected_punches("CLOCK")
        async def endpoint(**kwargs):
            raise error

        with patch("app.attendance.infrastructure.punch_exceptions.record_rejected_punch", new_callable=AsyncMock) as record:
            with self.assertRaises(PunchRuleViolation) as rejected:
                await endpoint(user_id=self.user_id, policy=self.policy, latitude=14.5, longitude=121.0, gps_accuracy_meters=10)
        self.assertIs(rejected.exception, error)
        data = record.call_args.kwargs
        self.assertEqual(data["requested_user_id"], self.user_id)
        self.assertEqual(data["metadata"]["location_report"]["latitude"], 14.5)

    async def test_success_and_technical_failures_do_not_create_exceptions(self):
        @log_rejected_punches("CLOCK")
        async def success(**kwargs):
            return "accepted"

        @log_rejected_punches("CLOCK")
        async def failure(**kwargs):
            raise RuntimeError("Database unavailable")

        with patch("app.attendance.infrastructure.punch_exceptions.record_rejected_punch", new_callable=AsyncMock) as record:
            self.assertEqual(await success(user_id=self.user_id, policy=self.policy), "accepted")
            with self.assertRaises(RuntimeError):
                await failure(user_id=self.user_id, policy=self.policy)
            record.assert_not_awaited()

    async def test_break_image_rejection_preserves_status_and_break_action(self):
        @log_rejected_punches("BREAK")
        async def endpoint(**kwargs):
            raise HTTPException(status_code=413, detail="Face image exceeds the size limit.")

        with patch("app.attendance.infrastructure.punch_exceptions.record_rejected_punch", new_callable=AsyncMock) as record:
            with self.assertRaises(HTTPException) as rejected:
                await endpoint(user_id=self.user_id, policy=self.policy, break_type="meal_break_in_at")
        self.assertEqual(rejected.exception.status_code, 413)
        self.assertEqual(record.call_args.kwargs["punch_action"], "meal_break_in_at")

    async def test_persistence_uses_independent_session_and_commits_metadata(self):
        session = MagicMock()
        session.commit = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        metadata = {"location_report": {"latitude": 14.5, "longitude": 121.0}}
        with patch("app.attendance.infrastructure.punch_exceptions.AsyncSessionLocal", factory):
            await record_rejected_punch(
                requested_user_id=self.user_id, punch_action="CLOCK",
                attempted_at=datetime.now(timezone.utc), policy=self.policy, metadata=metadata,
                error=PunchRuleViolation("Too early", "CLOCK_IN_TOO_EARLY", {"allowance_minutes": 30}),
            )
        session.commit.assert_awaited_once()
        row = session.add.call_args.args[0]
        self.assertEqual(row.punch_metadata, metadata)
        self.assertTrue(row.identity_verified)
        self.assertEqual(row.rule_code, "CLOCK_IN_TOO_EARLY")
        self.assertEqual(row.punch_action, "CLOCK_IN")

    async def test_logging_failure_is_explicit_not_a_silent_success(self):
        session = MagicMock()
        session.commit = AsyncMock(side_effect=SQLAlchemyError("Unavailable"))
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch("app.attendance.infrastructure.punch_exceptions.AsyncSessionLocal", factory):
            with self.assertLogs("app.attendance.infrastructure.punch_exceptions", level="ERROR"):
                with self.assertRaises(HTTPException) as error:
                    await record_rejected_punch(
                        requested_user_id=self.user_id, punch_action="CLOCK",
                        attempted_at=datetime.now(timezone.utc), policy=self.policy, metadata={},
                        error=ValueError("Invalid punch"),
                    )
        self.assertEqual(error.exception.status_code, 503)
