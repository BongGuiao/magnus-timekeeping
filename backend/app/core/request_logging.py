import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import perf_counter_ns
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record.msg, default=str, separators=(",", ":"))


class _RequestFileHandler(RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        logging.getLogger(__name__).error(
            "Failed to persist structured application logs; check log volume space and permissions.",
            exc_info=True,
        )


def configure_request_logger(log_directory: str) -> logging.Logger:
    return _configure_json_file_logger(
        logger_name=f"magnus.requests.{os.getpid()}",
        file_name=f"requests-{os.getpid()}.ndjson",
        log_directory=log_directory,
    )


def configure_audit_logger(log_directory: str) -> logging.Logger:
    return _configure_json_file_logger(
        logger_name="magnus.audit",
        file_name=f"location-audit-{os.getpid()}.ndjson",
        log_directory=log_directory,
    )


def _configure_json_file_logger(
    *,
    logger_name: str,
    file_name: str,
    log_directory: str,
) -> logging.Logger:
    directory = Path(log_directory)
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(logger_name)
    if not logger.handlers:
        handler = _RequestFileHandler(
            directory / file_name,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(_JSONFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


class RequestLoggingMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        log_directory: str = "logs",
        logger: logging.Logger | None = None,
    ) -> None:
        self.app = app
        self.logger = logger if logger is not None else configure_request_logger(log_directory)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        root_path = scope.get("root_path", "")
        if root_path and path.startswith(root_path + "/"):
            path = path[len(root_path):]
        if scope["type"] != "http" or not (
            path == "/locations" or path.startswith("/locations/")
        ):
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        started = perf_counter_ns()
        status_code = 500
        response_bytes = 0
        completed = False
        response_finished: int | None = None
        error_type: str | None = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_bytes, completed, response_finished
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                message = {
                    **message,
                    "headers": [*headers, (b"x-request-id", request_id.encode("ascii"))],
                }
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b""))
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True
                response_finished = perf_counter_ns()

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as error:
            error_type = type(error).__name__
            raise
        finally:
            route = scope.get("route")
            route_path = getattr(route, "path", "/locations/<unmatched>")
            failed = status_code >= 400 or error_type is not None or not completed
            event: dict[str, object] = {
                "@timestamp": datetime.now(timezone.utc).isoformat(),
                "ecs.version": "8.11.0",
                "service.name": "magnus-timekeeping",
                "event.dataset": "magnus.requests",
                "event.kind": "event",
                "event.category": ["web"],
                "event.type": ["access"],
                "event.action": "http_request",
                "event.duration": (
                    response_finished if response_finished is not None else perf_counter_ns()
                ) - started,
                "event.outcome": "failure" if failed else "success",
                "http.request.id": request_id,
                "http.request.method": scope["method"],
                "http.response.status_code": status_code,
                "http.response.body.bytes": response_bytes,
                "http.response.completed": completed,
                "url.path": route_path,
                "process.pid": os.getpid(),
                "log.level": "error" if status_code >= 500 or error_type else (
                    "warning" if failed else "info"
                ),
            }
            if error_type is not None:
                event["error.type"] = error_type
            self.logger.log(
                logging.ERROR if status_code >= 500 or error_type else (
                    logging.WARNING if failed else logging.INFO
                ),
                event,
            )
