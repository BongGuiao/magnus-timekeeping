import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from starlette.requests import Request

from app.filemaintenance.devices.infrastructure.router import (
    AttendanceDeviceEnrollmentSchema,
    enroll_attendance_device,
)


class DeviceEnrollmentMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_platform_and_application_version_are_not_swapped(self):
        for platform, version in (("ANDROID", "57.0.9"), ("IOS", "1.2.3"), ("WEB", None)):
            with self.subTest(platform=platform):
                user_id = uuid4()
                payload = AttendanceDeviceEnrollmentSchema(
                    user_id=user_id, device_uuid="test-device", device_name="Test device",
                    public_key_jwk={}, platform=platform, app_version=version,
                    os_version="Test OS",
                )
                request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
                result = {"id": str(uuid4()), "device_uuid": "test-device", "registration_status": "PENDING"}
                with patch("app.filemaintenance.devices.infrastructure.router.register_attendance_device", new_callable=AsyncMock, return_value=result) as register, \
                     patch("app.filemaintenance.devices.infrastructure.router.refresh_pending_device_snapshot"), \
                     patch("app.filemaintenance.devices.infrastructure.router.log_entity_action", new_callable=AsyncMock):
                    await enroll_attendance_device(
                        payload, request, claims={"sub": str(user_id), "role": "employee", "email": "test@example.invalid"},
                        uow=MagicMock(), es_client=None,
                    )
                self.assertEqual(register.call_args.kwargs["platform"], platform)
                self.assertEqual(register.call_args.kwargs["app_version"], version)
                self.assertEqual(register.call_args.kwargs["os_version"], "Test OS")
