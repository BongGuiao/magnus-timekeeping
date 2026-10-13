from datetime import datetime, timezone
from functools import wraps
import logging
from typing import Any, Awaitable, Callable, ParamSpec, TypeVar
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.attendance.infrastructure.clock_policy import AttendanceClockPolicy
from app.attendance.infrastructure.db_model import PunchExceptionModel
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")


class PunchRuleViolation(ValueError):
    def __init__(self, reason: str, rule_code: str, context: dict[str, Any]):
        super().__init__(reason)
        self.rule_code = rule_code
        self.context = context


def build_punch_metadata(
    latitude: float | None,
    longitude: float | None,
    gps_accuracy_meters: float | None,
    policy: AttendanceClockPolicy,
    attempted_at: datetime,
) -> dict[str, Any]:
    available = latitude is not None and longitude is not None
    return {
        "location_report": {
            "status": "REPORTED" if available else "UNAVAILABLE",
            "latitude": latitude,
            "longitude": longitude,
            "accuracy_meters": gps_accuracy_meters,
            "received_at": attempted_at.isoformat(),
            "source": "CLIENT_GPS",
            "verified": False,
        },
        "clock_policy": policy.as_metadata(),
        "client_source": "native" if policy.is_native else "browser",
    }


async def record_rejected_punch(
    *,
    requested_user_id: UUID,
    punch_action: str,
    attempted_at: datetime,
    policy: AttendanceClockPolicy,
    metadata: dict[str, Any],
    error: ValueError | HTTPException,
) -> None:
    violation = error if isinstance(error, PunchRuleViolation) else None
    record = PunchExceptionModel(
        requested_user_id=requested_user_id,
        attempted_at=attempted_at,
        punch_action="CLOCK_IN" if violation and violation.rule_code == "CLOCK_IN_TOO_EARLY" else punch_action,
        rule_code=violation.rule_code if violation else "PUNCH_VALIDATION_FAILED",
        reason=str(error) if isinstance(error, ValueError) else str(error.detail),
        validation_context=violation.context if violation else {},
        identity_verified=True if violation else None,
        client_channel=policy.channel,
        punch_metadata=metadata,
    )
    try:
        # The rejected attendance transaction has already rolled back.
        async with AsyncSessionLocal() as session:
            session.add(record)
            await session.commit()
    except SQLAlchemyError as failure:
        logger.exception("Could not persist rejected punch for requested user %s", requested_user_id)
        raise HTTPException(
            status_code=503,
            detail="The punch was rejected, but its exception could not be recorded. Please contact support.",
        ) from failure


def log_rejected_punches(action: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    def decorate(endpoint: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(endpoint)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            attempted_at = datetime.now(timezone.utc)
            try:
                return await endpoint(*args, **kwargs)
            except (ValueError, HTTPException) as error:
                if isinstance(error, HTTPException) and error.status_code not in (400, 403, 404, 413, 422):
                    raise
                user_id = kwargs.get("user_id")
                policy = kwargs.get("policy")
                if not isinstance(user_id, UUID) or not isinstance(policy, AttendanceClockPolicy):
                    raise
                metadata = build_punch_metadata(
                    kwargs.get("latitude"), kwargs.get("longitude"),
                    kwargs.get("gps_accuracy_meters"), policy, attempted_at,
                )
                await record_rejected_punch(
                    requested_user_id=user_id,
                    punch_action=str(kwargs.get("break_type", action)),
                    attempted_at=attempted_at,
                    policy=policy,
                    metadata=metadata,
                    error=error,
                )
                raise
        return wrapped
    return decorate
