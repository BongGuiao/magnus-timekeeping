import base64
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from app.attendance.domain.offline import (
    OFFLINE_LIFETIME, circle_contains, event_message, fingerprint, validate_capture,
)
from app.attendance.infrastructure.offline_gateway import (
    SqlAlchemyOfflineAttendanceGateway, TransactionAttendanceUow, photo_cipher, snapshot_json,
)
from app.attendance.infrastructure.offline_models import OfflinePermitModel, OfflinePunchEventModel
from app.core.config import settings


class OfflinePolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 30, 1, tzinfo=timezone.utc)
        self.permit = {
            "issued_at": (self.now - timedelta(hours=1)).isoformat(),
            "expires_at": (self.now + timedelta(hours=23)).isoformat(),
        }
        self.payload = {
            "captured_at": self.now.isoformat(), "gps_at": self.now.isoformat(),
            "latitude": 14.6, "longitude": 121, "accuracy": 10,
            "action": "clock_in", "sequence": 1,
        }

    def test_permit_lifetime_and_original_capture_time_not_upload_time(self):
        self.assertEqual(OFFLINE_LIFETIME, timedelta(hours=24))
        validate_capture(self.payload, self.permit, self.now + timedelta(days=3))

    def test_expiry_is_exclusive_and_future_and_stale_gps_are_rejected(self):
        for changes in (
            {"captured_at": self.permit["expires_at"]},
            {"captured_at": (self.now + timedelta(minutes=3)).isoformat()},
            {"gps_at": (self.now - timedelta(seconds=61)).isoformat()},
            {"accuracy": 0}, {"latitude": float("nan")},
            {"longitude": 181}, {"sequence": 0}, {"action": "toggle"},
            {"captured_at": "2026-10-30T01:00:00"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_capture({**self.payload, **changes}, self.permit, self.now)

    def test_circle_gps_uncertainty_and_max_accuracy_are_enforced(self):
        fence = {"shape": "CIRCLE", "latitude": 14.6, "longitude": 121,
                 "radius_meters": 100, "maximum_gps_accuracy_meters": 30}
        self.assertTrue(circle_contains(fence, 14.6, 121, 30))
        self.assertFalse(circle_contains(fence, 14.6, 121, 31))
        self.assertFalse(circle_contains(fence, 14.6, 121.0009, 20))
        self.assertFalse(circle_contains({**fence, "radius_meters": 0}, 14.6, 121, 10))

    def test_policy_fingerprint_is_stable_and_changes_with_boundary(self):
        self.assertEqual(fingerprint({"b": 2, "a": 1}), fingerprint({"a": 1, "b": 2}))
        self.assertNotEqual(fingerprint({"radius": 100}), fingerprint({"radius": 101}))

    def test_schedule_snapshot_uses_iso_timestamps_supported_by_native_javascript(self):
        self.assertEqual(snapshot_json({"start": self.now})["start"], "2026-10-30T01:00:00+00:00")


class FakeSession:
    def __init__(self):
        self.events = {}
        self.permits = {}
        self.pending = []
        self.flush = AsyncMock()
        self.scalar = AsyncMock(return_value=None)
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.close = AsyncMock()
        self.effects = []

    async def get(self, model, key):
        return (self.events if model is OfflinePunchEventModel else self.permits).get(key)

    def add(self, value):
        self.pending.append(value)

    def begin_nested(self):
        session = self

        class Savepoint:
            async def __aenter__(self):
                self.previous = list(session.effects)
                return self

            async def __aexit__(self, kind, value, traceback):
                if kind:
                    session.effects = self.previous
                return False
        return Savepoint()


class FakeUow:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.pending = []
        return self

    async def __aexit__(self, kind, value, traceback):
        if not kind:
            for event in self.session.pending:
                target = self.session.permits if isinstance(event, OfflinePermitModel) else self.session.events
                target[event.id] = event
        self.session.pending = []
        return False


class OfflineIngestionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.user_id, self.device_id, self.permit_id = uuid4(), uuid4(), uuid4()
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        numbers = self.private_key.public_key().public_numbers()

        def encoded(value):
            return base64.urlsafe_b64encode(value.to_bytes(32, "big")).decode().rstrip("=")
        self.credential = SimpleNamespace(public_key_jwk={
            "kty": "EC", "crv": "P-256", "x": encoded(numbers.x), "y": encoded(numbers.y),
        })
        self.user = SimpleNamespace(id=self.user_id, employee_id=uuid4(), is_active=True, account_status="ACTIVE")
        self.device = SimpleNamespace(
            id=self.device_id, device_uuid="phone", platform="ANDROID", is_active=True,
            registration_status="APPROVED", revoked_at=None,
        )
        self.session = FakeSession()
        self.gateway = SqlAlchemyOfflineAttendanceGateway(FakeUow(self.session), Mock())
        self.gateway._device = AsyncMock(return_value=(self.user, self.device, self.credential))
        self.gateway._apply = AsyncMock(side_effect=self.apply)
        now = datetime.now(timezone.utc)
        snapshot = {
            "issued_at": (now - timedelta(hours=1)).isoformat(),
            "expires_at": (now + timedelta(hours=23)).isoformat(),
        }
        self.session.permits[self.permit_id] = OfflinePermitModel(
            id=self.permit_id, user_id=self.user_id, device_id=self.device_id,
            snapshot=snapshot, issued_at=now - timedelta(hours=1), expires_at=now + timedelta(hours=23),
        )
        token = jwt.encode(
            {"aud": "magnus-offline-v1", "permit_id": str(self.permit_id), "snapshot_hash": fingerprint(snapshot)},
            settings.SECRET_KEY, algorithm=settings.ALGORITHM,
        )
        self.image = b"test photo bytes"
        self.payload = {
            "event_id": str(uuid4()), "user_id": str(self.user_id), "device_uuid": "phone",
            "permit_token": token, "captured_at": now.isoformat(), "gps_at": now.isoformat(),
            "latitude": 14.6, "longitude": 121, "accuracy": 10, "action": "clock_in",
            "sequence": 1, "photo_hash": hashlib.sha256(self.image).hexdigest(),
            "previous_at": None, "clock_trusted": True,
        }
        self.lock = patch("app.attendance.infrastructure.offline_gateway.lock_attendance_user", new=AsyncMock())
        self.lock.start()
        self.addCleanup(self.lock.stop)

    async def apply(self, session, user, device, permit, event, image):
        session.effects.append(event.id)
        event.status = "ACCEPTED"
        event.encrypted_photo = None

    def signed(self, payload=None):
        text = json.dumps(payload or self.payload, separators=(",", ":"))
        signature = self.private_key.sign(event_message(text), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(signature)
        raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return text, base64.urlsafe_b64encode(raw).decode().rstrip("=")

    async def submit(self, payload=None, image=None):
        text, signature = self.signed(payload)
        return await self.gateway.ingest(self.user_id, text, signature, image or self.image)

    async def test_duplicate_upload_returns_same_receipt_and_does_not_apply_twice(self):
        first = await self.submit()
        second = await self.submit()
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "ACCEPTED")
        self.assertEqual(len(self.session.events), 1)
        self.assertEqual(len(self.session.effects), 1)
        self.gateway._apply.assert_awaited_once()

    async def test_event_id_reuse_with_changed_payload_is_rejected(self):
        await self.submit()
        with self.assertRaisesRegex(ValueError, "different content"):
            await self.submit({**self.payload, "accuracy": 11})

    async def test_tampered_signature_photo_and_employee_are_rejected(self):
        text, signature = self.signed()
        with self.assertRaisesRegex(ValueError, "signature"):
            await self.gateway.ingest(self.user_id, text.replace('"sequence":1', '"sequence":2'), signature, self.image)
        with self.assertRaisesRegex(ValueError, "photo"):
            await self.submit(image=b"changed photo")
        with self.assertRaisesRegex(ValueError, "authenticated employee"):
            await self.submit({**self.payload, "user_id": str(uuid4())})
        self.assertEqual(len(self.session.events), 0)

    async def test_locked_or_conflicting_event_is_retained_and_attendance_effect_is_rolled_back(self):
        async def locked(session, user, device, permit, event, image):
            session.effects.append("must be rolled back")
            raise ValueError("Payroll is locked; HR review required.")
        self.gateway._apply.side_effect = locked
        result = await self.submit()
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertIn("locked", result["reason"])
        self.assertEqual(self.session.effects, [])
        stored = next(iter(self.session.events.values()))
        self.assertNotEqual(stored.encrypted_photo, self.image)
        self.assertEqual(photo_cipher().decrypt(stored.encrypted_photo), self.image)

    async def test_expired_capture_gets_durable_rejection_without_applying_attendance(self):
        permit = self.session.permits[self.permit_id]
        result = await self.submit({**self.payload, "captured_at": permit.snapshot["expires_at"]})
        self.assertEqual(result["status"], "REJECTED")
        self.gateway._apply.assert_not_awaited()
        self.assertIsNone(next(iter(self.session.events.values())).encrypted_photo)

    async def test_changed_permit_snapshot_is_rejected(self):
        self.session.permits[self.permit_id].snapshot["expires_at"] = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        with self.assertRaisesRegex(ValueError, "authorization"):
            await self.submit()

    async def test_database_failure_does_not_return_a_success_receipt(self):
        self.session.flush.side_effect = RuntimeError("Database unavailable")
        with self.assertRaisesRegex(RuntimeError, "Database unavailable"):
            await self.submit()
        self.assertEqual(self.session.events, {})

    async def test_bound_attendance_uow_never_commits_or_closes_ingestion_session(self):
        async with TransactionAttendanceUow(self.session) as bound:
            self.assertIs(bound.session, self.session)
        self.session.commit.assert_not_awaited()
        self.session.rollback.assert_not_awaited()
        self.session.close.assert_not_awaited()

    async def test_preparation_issues_signed_24_hour_device_bound_snapshot(self):
        self.gateway._policy = AsyncMock(return_value=[{"shape": "CIRCLE"}])
        self.gateway._schedules = AsyncMock(return_value={})
        with patch("app.attendance.infrastructure.offline_gateway.GetLastAttendanceUseCase") as get_last:
            get_last.return_value.execute = AsyncMock(return_value=None)
            result = await self.gateway.prepare(self.user_id, self.device.device_uuid)
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["user_id"], str(self.user_id))
        self.assertEqual(snapshot["device_uuid"], self.device.device_uuid)
        self.assertEqual(datetime.fromisoformat(snapshot["expires_at"]) - datetime.fromisoformat(snapshot["issued_at"]), timedelta(hours=24))
        claims = jwt.decode(result["token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM], audience="magnus-offline-v1")
        self.assertEqual(claims["snapshot_hash"], fingerprint(snapshot))
        self.assertIn(UUID(snapshot["permit_id"]), self.session.permits)

    async def test_preparation_does_not_authorize_web_unapproved_or_inactive_devices(self):
        for changes in ({"platform": "WEB"}, {"registration_status": "PENDING"}, {"is_active": False}):
            with self.subTest(changes=changes):
                original = {key: getattr(self.device, key) for key in changes}
                for key, value in changes.items():
                    setattr(self.device, key, value)
                with self.assertRaisesRegex(ValueError, "approved Android/iOS"):
                    await self.gateway.prepare(self.user_id, self.device.device_uuid)
                for key, value in original.items():
                    setattr(self.device, key, value)

    async def test_revoked_device_and_lost_clock_reference_require_review_before_punching(self):
        permit = self.session.permits[self.permit_id]
        event = OfflinePunchEventModel(id=uuid4(), payload=self.payload)
        self.device.registration_status = "REVOKED"
        with self.assertRaisesRegex(ValueError, "eligibility changed"):
            await SqlAlchemyOfflineAttendanceGateway._apply(
                self.gateway, self.session, self.user, self.device, permit, event, self.image,
            )
        self.device.registration_status = "APPROVED"
        event.payload = {**self.payload, "clock_trusted": False}
        with self.assertRaisesRegex(ValueError, "time reference"):
            await SqlAlchemyOfflineAttendanceGateway._apply(
                self.gateway, self.session, self.user, self.device, permit, event, self.image,
            )

    async def test_conflicting_previous_punch_and_locked_attendance_are_preserved_for_review(self):
        from app.attendance.application.use_case import PUNCH_FIELDS
        permit = self.session.permits[self.permit_id]
        fence = {"shape": "CIRCLE", "latitude": 14.6, "longitude": 121,
                 "radius_meters": 100, "maximum_gps_accuracy_meters": 30}
        permit.snapshot["geofences"] = [fence]
        self.gateway._policy = AsyncMock(return_value=[fence])
        previous = datetime.now(timezone.utc) - timedelta(hours=2)
        latest = SimpleNamespace(**{field: None for field in PUNCH_FIELDS})
        latest.clock_in_at = previous
        latest.is_locked = True
        self.session.scalar.return_value = latest
        event = OfflinePunchEventModel(id=uuid4(), payload=self.payload,
                                        captured_at=datetime.now(timezone.utc))
        with self.assertRaisesRegex(ValueError, "sequence"):
            await SqlAlchemyOfflineAttendanceGateway._apply(
                self.gateway, self.session, self.user, self.device, permit, event, self.image,
            )
        event.payload = {**self.payload, "action": "clock_out", "previous_at": previous.isoformat()}
        with self.assertRaisesRegex(ValueError, "locked"):
            await SqlAlchemyOfflineAttendanceGateway._apply(
                self.gateway, self.session, self.user, self.device, permit, event, self.image,
            )

    async def test_processed_payroll_blocks_mutation_even_if_attendance_is_not_locked(self):
        from dataclasses import asdict
        from app.attendance.application.use_case import PUNCH_FIELDS, ScheduleDayConfiguration
        captured = datetime.now(timezone.utc)
        previous = captured - timedelta(hours=2)
        latest = SimpleNamespace(**{field: None for field in PUNCH_FIELDS})
        latest.clock_in_at, latest.work_date, latest.is_locked = previous, captured.date(), False
        schedule = ScheduleDayConfiguration(work_type="REG", expected_clock_in_at=None, expected_clock_out_at=None)
        fence = {"shape": "CIRCLE", "latitude": 14.6, "longitude": 121,
                 "radius_meters": 100, "maximum_gps_accuracy_meters": 30}
        permit = self.session.permits[self.permit_id]
        permit.snapshot.update(geofences=[fence], schedules={captured.date().isoformat(): snapshot_json(asdict(schedule))})
        self.gateway._policy = AsyncMock(return_value=[fence])
        self.session.scalar.side_effect = [latest, uuid4()]
        self.session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [SimpleNamespace(
            id=uuid4(), status="OPEN", locked_at=None, attendance_finalized_at=None,
        )]))
        event = OfflinePunchEventModel(id=uuid4(), captured_at=captured, payload={
            **self.payload, "action": "clock_out", "previous_at": previous.isoformat(),
        })
        with patch("app.attendance.infrastructure.offline_gateway.ClockAttendanceUseCase._resolve_schedule_day",
                   new=AsyncMock(return_value=schedule)):
            with self.assertRaisesRegex(ValueError, "already processed"):
                await SqlAlchemyOfflineAttendanceGateway._apply(
                    self.gateway, self.session, self.user, self.device, permit, event, self.image,
                )
        self.assertIsNone(latest.clock_out_at)


class OfflineCaptureUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_uses_verified_capture_time_instead_of_current_server_time(self):
        from backend.tests.test_early_clock_in import EarlyClockInUseCaseTests
        from app.attendance.application.use_case import ClockAttendanceInputDTO
        fixture = EarlyClockInUseCaseTests()
        fixture.setUp()
        captured_at = fixture.now.astimezone(timezone.utc)
        result = await fixture.use_case._execute(ClockAttendanceInputDTO(
            user_id=fixture.user_id, image_bytes=b"photo",
            captured_at=captured_at, requested_action="clock_in",
        ))
        self.assertEqual(datetime.fromisoformat(result.timestamp), captured_at)
        self.assertEqual(fixture.attendance.add.call_args.args[0].work_date, fixture.now.date())

    async def test_clock_out_event_cannot_turn_into_clock_in_when_no_shift_is_open(self):
        from backend.tests.test_early_clock_in import EarlyClockInUseCaseTests
        from app.attendance.application.use_case import ClockAttendanceInputDTO
        fixture = EarlyClockInUseCaseTests()
        fixture.setUp()
        with self.assertRaisesRegex(ValueError, "conflicts"):
            await fixture.use_case._execute(ClockAttendanceInputDTO(
                user_id=fixture.user_id, image_bytes=b"photo",
                captured_at=fixture.now.astimezone(timezone.utc), requested_action="clock_out",
            ))
        fixture.attendance.add.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
