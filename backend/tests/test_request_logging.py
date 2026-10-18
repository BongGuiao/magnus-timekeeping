import asyncio
import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI, HTTPException
from starlette.types import Message, Scope

from app.core.exception_handlers import register_exception_handlers
from app.core.request_logging import RequestLoggingMiddleware, configure_request_logger


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.events.append(record.msg)


class RequestLoggingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.handler = _CaptureHandler()
        self.logger = logging.Logger("request-logging-test", logging.INFO)
        self.logger.addHandler(self.handler)
        self.app = FastAPI()
        register_exception_handlers(self.app)
        self.private_value = "private-body-token-email"

        @self.app.post("/locations/create", status_code=201)
        async def create(payload: dict):
            return payload

        @self.app.get("/locations/list")
        async def list_locations():
            return []

        @self.app.get("/locations/unauthorized")
        async def unauthorized():
            raise HTTPException(status_code=401, detail="Not authenticated")

        @self.app.get("/locations/invalid")
        async def invalid():
            raise ValueError(self.private_value)

        @self.app.get("/locations/failure")
        async def failure():
            raise RuntimeError(self.private_value)

        @self.app.get("/locations/crash")
        async def crash():
            raise ZeroDivisionError(self.private_value)

        @self.app.get("/locations/{location_id}")
        async def get_location(location_id: UUID):
            return {"id": str(location_id)}

        self.middleware = RequestLoggingMiddleware(self.app, logger=self.logger)

    async def request(
        self,
        path: str,
        *,
        method: str = "GET",
        root_path: str = "",
    ) -> list[Message]:
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "root_path": root_path,
            "query_string": b"token=private-query",
            "headers": [
                (b"content-type", b"application/json"),
                (b"authorization", b"Bearer private-header"),
                (b"x-request-id", b"untrusted-client-value"),
            ],
            "server": ("localhost", 80),
            "client": ("127.0.0.1", 1234),
        }
        messages: list[Message] = []
        sent_body = False

        async def receive() -> Message:
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {
                    "type": "http.request",
                    "body": json.dumps({"secret": self.private_value}).encode(),
                    "more_body": False,
                }
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            messages.append(message)

        await self.middleware(scope, receive, send)
        return messages

    async def test_success_and_response_are_preserved(self) -> None:
        messages = await self.request("/locations/create", method="POST")
        self.assertEqual(messages[0]["status"], 201)
        body = b"".join(m.get("body", b"") for m in messages)
        self.assertEqual(json.loads(body), {"secret": self.private_value})
        event = self.handler.events[0]
        self.assertEqual(event["http.response.status_code"], 201)
        self.assertEqual(event["http.response.body.bytes"], len(body))
        self.assertEqual(event["event.outcome"], "success")
        self.assertTrue(event["http.response.completed"])
        self.assertIsInstance(event["event.duration"], int)
        self.assertGreaterEqual(event["event.duration"], 0)
        headers = dict(messages[0]["headers"])
        self.assertEqual(headers[b"x-request-id"].decode(), event["http.request.id"])
        UUID(str(event["http.request.id"]))

    async def test_template_and_privacy(self) -> None:
        location_id = "b11fa7cd-2697-4c0b-8c7c-81e403db314d"
        await self.request(f"/locations/{location_id}")
        event = self.handler.events[0]
        self.assertEqual(event["url.path"], "/locations/{location_id}")
        serialized = json.dumps(event)
        for private in (
            location_id, self.private_value, "private-header",
            "private-query", "untrusted-client-value", "127.0.0.1",
        ):
            self.assertNotIn(private, serialized)

    async def test_handled_errors_and_validation(self) -> None:
        for path, expected in (
            ("/locations/unauthorized", 401),
            ("/locations/invalid", 400),
            ("/locations/failure", 500),
            ("/locations/not-a-uuid", 422),
        ):
            with self.subTest(path=path):
                messages = await self.request(path)
                self.assertEqual(messages[0]["status"], expected)
                event = self.handler.events[-1]
                self.assertEqual(event["http.response.status_code"], expected)
                self.assertEqual(event["event.outcome"], "failure")
                self.assertNotIn(self.private_value, json.dumps(event))

    async def test_unhandled_error_is_logged_once_and_reraised(self) -> None:
        with self.assertRaises(ZeroDivisionError):
            await self.request("/locations/crash")
        self.assertEqual(len(self.handler.events), 1)
        event = self.handler.events[0]
        self.assertEqual(event["http.response.status_code"], 500)
        self.assertEqual(event["error.type"], "ZeroDivisionError")
        self.assertEqual(event["event.outcome"], "failure")
        self.assertNotIn(self.private_value, json.dumps(event))

    async def test_other_routes_are_not_logged(self) -> None:
        for path in ("/docs", "/auth/login", "/locations-extra", "/attendance/last", "/attendance/clock-policy"):
            await self.request(path)
        self.assertEqual(self.handler.events, [])

    async def test_attendance_clock_and_break_are_logged(self) -> None:
        @self.app.post("/attendance/clock", status_code=201)
        async def clock():
            return {"ok": True}

        @self.app.post("/attendance/clock-break")
        async def clock_break():
            raise ValueError(self.private_value)

        await self.request("/attendance/clock", method="POST")
        await self.request("/attendance/clock-break", method="POST")
        clock_event, break_event = self.handler.events
        self.assertEqual(clock_event["url.path"], "/attendance/clock")
        self.assertEqual(clock_event["http.response.status_code"], 201)
        self.assertEqual(clock_event["event.outcome"], "success")
        self.assertEqual(break_event["url.path"], "/attendance/clock-break")
        self.assertEqual(break_event["http.response.status_code"], 400)
        self.assertEqual(break_event["event.outcome"], "failure")
        self.assertNotIn(self.private_value, json.dumps(self.handler.events))

    async def test_unmatched_path_is_redacted(self) -> None:
        await self.request("/locations/private-path/unknown")
        self.assertEqual(self.handler.events[0]["url.path"], "/locations/<unmatched>")

    async def test_root_path(self) -> None:
        await self.request("/api/locations/list", root_path="/api")
        self.assertEqual(self.handler.events[0]["url.path"], "/locations/list")

    async def test_streamed_response_counts_all_chunks(self) -> None:
        async def stream(scope, receive, send):
            scope["route"] = SimpleNamespace(path="/locations/list")
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"abc", "more_body": True})
            await send({"type": "http.response.body", "body": b"de"})

        self.middleware = RequestLoggingMiddleware(stream, logger=self.logger)
        await self.request("/locations/list")
        self.assertEqual(self.handler.events[0]["http.response.body.bytes"], 5)
        self.assertTrue(self.handler.events[0]["http.response.completed"])

    async def test_cancelled_request_is_not_reported_as_success(self) -> None:
        async def cancelled(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise asyncio.CancelledError()

        self.middleware = RequestLoggingMiddleware(cancelled, logger=self.logger)
        with self.assertRaises(asyncio.CancelledError):
            await self.request("/locations/list")
        self.assertFalse(self.handler.events[0]["http.response.completed"])
        self.assertEqual(self.handler.events[0]["event.outcome"], "failure")

    async def test_non_http_scope_passes_through(self) -> None:
        calls = []

        async def app(scope, receive, send):
            calls.append(scope["type"])

        middleware = RequestLoggingMiddleware(app, logger=self.logger)
        await middleware({"type": "lifespan"}, None, None)
        self.assertEqual(calls, ["lifespan"])
        self.assertEqual(self.handler.events, [])


class RequestFileTests(unittest.TestCase):
    def tearDown(self) -> None:
        import os
        logger = logging.getLogger(f"magnus.requests.{os.getpid()}")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def test_ndjson_and_bounded_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            logger = configure_request_logger(directory)
            self.assertIs(logger, configure_request_logger(directory))
            self.assertEqual(len(logger.handlers), 1)
            handler = logger.handlers[0]
            self.assertEqual(handler.maxBytes, 10 * 1024 * 1024)
            self.assertEqual(handler.backupCount, 5)
            handler.maxBytes = 100
            for number in range(30):
                logger.info({"number": number, "message": "x" * 50})
            handler.close()
            paths = list(Path(directory).glob("requests-*.ndjson*"))
            self.assertEqual(len(paths), 6)
            for path in paths:
                for line in path.read_text().splitlines():
                    self.assertIsInstance(json.loads(line)["number"], int)
            self.tearDown()

    def test_disk_failure_reports_error_without_failing_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            logger = configure_request_logger(directory)
            handler = logger.handlers[0]
            with patch.object(handler, "shouldRollover", side_effect=OSError("disk full")):
                with self.assertLogs("app.core.request_logging", level="ERROR") as captured:
                    logger.info({"event.outcome": "success"})
            self.assertIn("Failed to persist structured application logs", captured.output[0])
            self.tearDown()


if __name__ == "__main__":
    unittest.main()
