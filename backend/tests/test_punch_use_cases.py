import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.attendance.application.punch_use_cases import (
    IssueDeviceChallengeInput,
    IssueDeviceChallengeUseCase,
    SubmitBreakPunchInput,
    SubmitBreakPunchUseCase,
    SubmitClockPunchInput,
    SubmitClockPunchUseCase,
)
from app.attendance.domain.exceptions import PermissionDeniedError
from app.attendance.infrastructure.clock_policy import AttendanceClockPolicy
from app.attendance.infrastructure.clock_router import (
    MAX_FACE_IMAGE_BYTES,
    clock_attendance,
    clock_break_attendance,
)
from app.attendance.infrastructure.device_challenge_router import (
    DeviceChallengeRequest,
    create_device_challenge,
)
from app.attendance.infrastructure.punch_exceptions import log_rejected_punches
from app.core.database import init_db_models

# Rejected punches instantiate mapped models; register them all first, as the app does at startup.
init_db_models()

CLOCK_RESULT = SimpleNamespace(employee_code="EMP-1")


def proof(platform="ANDROID"):
    return {"device_id": str(uuid4()), "device_uuid": "device-1", "platform": platform}


class FakeProofs:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
        self.consume_calls, self.issue_calls = [], []

    async def consume(self, user_id, challenge_id, action, signature):
        self.consume_calls.append((user_id, challenge_id, action, signature))
        if self.error:
            raise self.error
        return self.result

    async def issue(self, user_id, device_uuid, action):
        self.issue_calls.append((user_id, device_uuid, action))
        return {"challenge_id": str(uuid4()), "message": "sign me", "expires_at": "soon"}


class ClockPunchUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = MagicMock(execute=AsyncMock(return_value=CLOCK_RESULT))
        self.refresher = MagicMock()
        self.audit = MagicMock(record=AsyncMock())

    def use_case(self, proofs):
        return SubmitClockPunchUseCase(self.clock, proofs, self.refresher, self.audit)

    def punch(self, **changes):
        values = dict(
            user_id=uuid4(), image_bytes=b"face", clock_channel={"channel": "mobile"},
            enforce_geofence=True, is_native=True, device_challenge_id=uuid4(), device_signature="sig",
            latitude=14.5, longitude=121.0, gps_accuracy_meters=10,
        )
        values.update(changes)
        return SubmitClockPunchInput(**values)

    async def dto(self, proofs, **changes):
        await self.use_case(proofs).execute(self.punch(**changes))
        return self.clock.execute.await_args.args[0]

    async def test_only_a_proven_native_android_or_ios_device_can_enable_wfh(self):
        for native, platform, approved, expected in (
            (True, "ANDROID", True, True),
            (True, "IOS", True, True),
            (True, "WEB", True, False),
            (False, "ANDROID", True, False),
            (True, "ANDROID", False, False),
        ):
            with self.subTest(native=native, platform=platform, approved=approved):
                proofs = FakeProofs(proof(platform)) if approved else FakeProofs(error=ValueError("unapproved"))
                dto = await self.dto(proofs, is_native=native)
                self.assertEqual(dto.allow_wfh, expected)
                self.assertTrue(dto.enforce_geofence)

    async def test_an_approved_device_is_recorded_on_the_punch(self):
        device = proof()
        dto = await self.dto(FakeProofs(device))
        self.assertTrue(dto.device_approved)
        self.assertEqual(dto.punch_metadata, {"device_proof": device})
        self.assertEqual(dto.clock_channel, {
            "channel": "mobile", "device_id": device["device_id"], "device_uuid": device["device_uuid"],
        })

    async def test_unapproved_or_missing_proof_flags_the_punch_instead_of_rejecting_it(self):
        cases = (
            (FakeProofs(error=ValueError("device revoked")), {}),
            (FakeProofs(proof()), {"device_challenge_id": None}),
            (FakeProofs(proof()), {"device_signature": None}),
        )
        for proofs, changes in cases:
            with self.subTest(changes=changes), self.assertLogs(
                "app.attendance.application.punch_use_cases", "WARNING",
            ):
                dto = await self.dto(proofs, **changes)
                self.assertFalse(dto.device_approved)
                self.assertIsNone(dto.punch_metadata)
                self.assertEqual(dto.clock_channel, {"channel": "mobile"})
        self.assertEqual(proofs.consume_calls, [])

    async def test_the_callers_channel_metadata_is_never_mutated(self):
        channel = {"channel": "mobile"}
        await self.dto(FakeProofs(proof()), clock_channel=channel)
        self.assertEqual(channel, {"channel": "mobile"})

    async def test_success_refreshes_the_employee_snapshot_and_audits_as_face_recognition(self):
        data = self.punch()
        await self.use_case(FakeProofs(proof())).execute(data)
        self.refresher.request_refresh.assert_called_once_with(data.user_id)
        kwargs = self.audit.record.await_args.kwargs
        self.assertEqual(
            (kwargs["user_id"], kwargs["action"], kwargs["resource"], kwargs["resource_id"], kwargs["after"]),
            ("face-recognition", "CREATE", "attendance", "EMP-1", CLOCK_RESULT),
        )

    async def test_a_rejected_punch_has_no_side_effects_and_keeps_its_error(self):
        self.clock.execute.side_effect = ValueError("outside geofence")
        with self.assertRaisesRegex(ValueError, "outside geofence"):
            await self.use_case(FakeProofs(proof())).execute(self.punch())
        self.refresher.request_refresh.assert_not_called()
        self.audit.record.assert_not_awaited()


class BreakPunchUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.record_break = MagicMock(execute=AsyncMock(return_value=SimpleNamespace(employee_code="EMP-1")))
        self.refresher = MagicMock()
        self.audit = MagicMock(record=AsyncMock())
        self.data = SubmitBreakPunchInput(
            user_id=uuid4(), break_type="meal_break_out_at", image_bytes=b"face",
            device_challenge_id=uuid4(), device_signature="sig", punch_metadata={"client_source": "native"},
        )

    def use_case(self, proofs):
        return SubmitBreakPunchUseCase(self.record_break, proofs, self.refresher, self.audit)

    async def test_the_proven_device_and_metadata_are_passed_to_the_break_use_case(self):
        device = proof()
        proofs = FakeProofs(device)
        await self.use_case(proofs).execute(self.data)
        self.assertEqual(proofs.consume_calls, [(self.data.user_id, self.data.device_challenge_id, "BREAK", "sig")])
        dto = self.record_break.execute.await_args.args[0]
        self.assertEqual((dto.break_type, dto.device_proof, dto.punch_metadata),
                         ("meal_break_out_at", device, {"client_source": "native"}))
        self.refresher.request_refresh.assert_called_once_with(self.data.user_id)
        self.assertEqual(self.audit.record.await_args.kwargs["resource"], "attendance_break")

    async def test_a_break_without_an_approved_device_is_rejected_unlike_clock_punches(self):
        with self.assertRaisesRegex(ValueError, "not approved"):
            await self.use_case(FakeProofs(error=ValueError("device is not approved"))).execute(self.data)
        self.record_break.execute.assert_not_awaited()
        self.refresher.request_refresh.assert_not_called()
        self.audit.record.assert_not_awaited()


class DeviceChallengeTests(unittest.IsolatedAsyncioTestCase):
    async def test_employees_can_only_request_challenges_for_themselves_but_admins_for_anyone(self):
        me, someone_else = uuid4(), uuid4()
        for actor, admin, target, allowed in (
            (me, False, me, True), (me, False, someone_else, False), (me, True, someone_else, True),
        ):
            with self.subTest(admin=admin, own=actor == target):
                proofs = FakeProofs()
                use_case = IssueDeviceChallengeUseCase(proofs)
                request = IssueDeviceChallengeInput(actor, admin, target, "device-1", "CLOCK")
                if allowed:
                    self.assertEqual((await use_case.execute(request))["message"], "sign me")
                    self.assertEqual(proofs.issue_calls, [(target, "device-1", "CLOCK")])
                else:
                    with self.assertRaises(PermissionDeniedError):
                        await use_case.execute(request)
                    self.assertEqual(proofs.issue_calls, [])

    async def test_router_maps_permission_to_403_and_a_bad_token_to_401(self):
        payload = DeviceChallengeRequest(user_id=uuid4(), device_uuid="device-1", action="CLOCK")
        denied = MagicMock(execute=AsyncMock(side_effect=PermissionDeniedError("nope")))
        with self.assertRaises(HTTPException) as error:
            await create_device_challenge(payload, claims={"sub": str(uuid4())}, use_case=denied)
        self.assertEqual((error.exception.status_code, error.exception.detail), (403, "nope"))
        with self.assertRaises(HTTPException) as error:
            await create_device_challenge(payload, claims={}, use_case=MagicMock())
        self.assertEqual(error.exception.status_code, 401)

    async def test_router_returns_the_issued_challenge_for_admins_flag(self):
        challenge = {"challenge_id": str(uuid4()), "message": "sign", "expires_at": "soon"}
        use_case = MagicMock(execute=AsyncMock(return_value=challenge))
        actor = uuid4()
        payload = DeviceChallengeRequest(user_id=actor, device_uuid="device-1", action="BREAK")
        response = await create_device_challenge(payload, claims={"sub": str(actor), "role": "admin"}, use_case=use_case)
        data = use_case.execute.await_args.args[0]
        self.assertEqual((data.actor_is_admin, data.action), (True, "BREAK"))
        self.assertEqual(response.data.message, "sign")


class ClockRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # The decorator persists rejected punches through its own DB session; never let tests reach it.
        patcher = patch("app.attendance.infrastructure.punch_exceptions.record_rejected_punch", AsyncMock())
        self.record_rejected = patcher.start()
        self.addCleanup(patcher.stop)

    def upload(self, content):
        return SimpleNamespace(read=AsyncMock(return_value=content))

    async def call_clock(self, use_case, upload, policy=None, **changes):
        values = dict(
            file=upload, user_id=uuid4(), clock_out_confirmed=True, latitude=14.5, longitude=121.0,
            gps_accuracy_meters=10, device_challenge_id=uuid4(), device_signature="s" * 86,
            policy=policy or AttendanceClockPolicy("mobile", True, "10.0.0.1", is_native=True), use_case=use_case,
        )
        values.update(changes)
        return await clock_attendance(**values)

    def result(self):
        return SimpleNamespace(
            employee_name="Ana", employee_code="EMP-1", action="CLOCK_IN", timestamp="t", schedule_template_id=None,
            approval_required=False, late_minutes=1, undertime_minutes=0, calculated_ot_minutes=0, overtime_hours=0,
            regular_overtime_minutes=0, regular_overtime_hours=0, night_differential_overtime_minutes=0,
            night_differential_overtime_hours=0, night_differential_hours=0,
        )

    async def test_policy_and_form_fields_are_translated_into_the_punch_input(self):
        use_case = MagicMock(execute=AsyncMock(return_value=self.result()))
        policy = AttendanceClockPolicy("mobile", True, "10.0.0.1", is_native=True)
        response = await self.call_clock(use_case, self.upload(b"face"), policy)
        data = use_case.execute.await_args.args[0]
        self.assertEqual(
            (data.image_bytes, data.clock_channel, data.enforce_geofence, data.is_native, data.clock_out_confirmed),
            (b"face", policy.as_metadata(), True, True, True),
        )
        self.assertEqual((response.data.employee_name, response.data.late_minutes), ("Ana", 1))

    async def test_empty_and_oversized_face_images_are_rejected_before_the_use_case_runs(self):
        use_case = MagicMock(execute=AsyncMock())
        for content, status_code in ((b"", 400), (b"x" * (MAX_FACE_IMAGE_BYTES + 1), 413)):
            with self.subTest(status_code=status_code), self.assertRaises(HTTPException) as error:
                await self.call_clock(use_case, self.upload(content))
            self.assertEqual(error.exception.status_code, status_code)
        use_case.execute.assert_not_awaited()
        self.assertEqual(self.record_rejected.await_count, 2)

    async def test_break_route_builds_location_metadata_from_the_policy(self):
        use_case = MagicMock(execute=AsyncMock(return_value=SimpleNamespace(
            employee_name="Ana", employee_code="EMP-1", action_recorded="meal_break_out_at", timestamp="t",
        )))
        policy = AttendanceClockPolicy("mobile", True, None, is_native=True)
        response = await clock_break_attendance(
            break_type="meal_break_out_at", user_id=uuid4(), file=self.upload(b"face"),
            device_challenge_id=uuid4(), device_signature="s" * 86, latitude=14.5, longitude=121.0,
            gps_accuracy_meters=10, policy=policy, use_case=use_case,
        )
        metadata = use_case.execute.await_args.args[0].punch_metadata
        self.assertEqual((metadata["client_source"], metadata["location_report"]["latitude"]), ("native", 14.5))
        self.assertEqual(response.data.action_recorded, "meal_break_out_at")

    async def test_rejected_punches_are_still_recorded_by_the_route_decorator(self):
        # The decorator reads user_id/policy/latitude... from the endpoint's keyword arguments.
        use_case = MagicMock(execute=AsyncMock(side_effect=ValueError("outside geofence")))
        self.assertTrue(hasattr(clock_attendance, "__wrapped__"))
        self.assertTrue(hasattr(clock_break_attendance, "__wrapped__"))
        with self.assertRaisesRegex(ValueError, "outside geofence"):
            await self.call_clock(use_case, self.upload(b"face"))
        self.record_rejected.assert_awaited_once()
        self.assertEqual(self.record_rejected.await_args.kwargs["punch_action"], "CLOCK")
