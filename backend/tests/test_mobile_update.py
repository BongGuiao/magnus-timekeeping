import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI

from app.core.mobile_update import router, settings


class MobileUpdateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.patches = patch.multiple(
            settings,
            MOBILE_ANDROID_LATEST_VERSION="",
            MOBILE_ANDROID_UPDATE_URL="",
            MOBILE_ANDROID_RELEASE_NOTES="",
            MOBILE_IOS_LATEST_VERSION="",
            MOBILE_IOS_UPDATE_URL="",
            MOBILE_IOS_RELEASE_NOTES="",
        )
        self.patches.start()
        self.addCleanup(self.patches.stop)

    async def get(self, platform):
        messages = []
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": "/api/mobile-update",
            "raw_path": b"/api/mobile-update", "query_string": f"platform={platform}".encode(),
            "headers": [], "client": ("127.0.0.1", 1), "server": ("test", 80),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await self.app(scope, receive, send)
        status = next(message["status"] for message in messages if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return status, json.loads(body)

    async def test_unconfigured_and_platform_specific_release(self):
        self.assertIsNone((await self.get("android"))[1]["data"])
        settings.MOBILE_ANDROID_LATEST_VERSION = "1.2.3"
        settings.MOBILE_ANDROID_UPDATE_URL = "https://updates.example.com/app.apk"
        settings.MOBILE_ANDROID_RELEASE_NOTES = "Attendance fixes"
        status, response = await self.get("android")
        self.assertEqual(status, 200)
        self.assertEqual(response["data"], {
            "version": "1.2.3", "url": "https://updates.example.com/app.apk",
            "release_notes": "Attendance fixes",
        })
        self.assertIsNone((await self.get("ios"))[1]["data"])

    async def test_invalid_configuration_fails_explicitly(self):
        for version, url in [
            ("1.2.3", ""), ("1.2", "https://example.com/app.apk"),
            ("1.2.3", "http://example.com/app.apk"),
            ("1.2.3", "https://user:pass@example.com/app.apk"),
            ("1.2.3", "https://[broken"),
        ]:
            with self.subTest(version=version, url=url):
                settings.MOBILE_ANDROID_LATEST_VERSION = version
                settings.MOBILE_ANDROID_UPDATE_URL = url
                with self.assertLogs("app.core.mobile_update", level="ERROR"):
                    status, _ = await self.get("android")
                self.assertEqual(status, 503)

    async def test_unsupported_platform_is_rejected(self):
        self.assertEqual((await self.get("web"))[0], 422)
