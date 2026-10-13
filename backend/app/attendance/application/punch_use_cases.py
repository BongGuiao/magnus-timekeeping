import logging
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from app.attendance.application.punch_ports import DeviceAction, DeviceProofService
from app.attendance.application.ports import AuditTrail, RecentAttendanceRefresher
from app.attendance.application.use_case import (
    ClockAttendanceInputDTO,
    ClockAttendanceOutputDTO,
    ClockAttendanceUseCase,
    RecordBreakInputDTO,
    RecordBreakOutputDTO,
    RecordBreakUseCase,
)
from app.attendance.domain.exceptions import PermissionDeniedError
from app.core.generics.uc_base import BaseUseCase

logger = logging.getLogger(__name__)

SYSTEM_ACTOR = "face-recognition"
NATIVE_PLATFORMS = ("ANDROID", "IOS")


@dataclass
class IssueDeviceChallengeInput:
    actor_id: UUID
    actor_is_admin: bool
    user_id: UUID
    device_uuid: str
    action: DeviceAction


class IssueDeviceChallengeUseCase(BaseUseCase[dict[str, str]]):
    def __init__(self, proofs: DeviceProofService):
        self._proofs = proofs

    async def _execute(self, data: IssueDeviceChallengeInput) -> dict[str, str]:
        if not data.actor_is_admin and data.actor_id != data.user_id:
            raise PermissionDeniedError(
                "You can only request device challenges for your own employee account."
            )
        return await self._proofs.issue(data.user_id, data.device_uuid, data.action)


@dataclass
class SubmitClockPunchInput:
    user_id: UUID
    image_bytes: bytes
    clock_channel: dict[str, Any]
    enforce_geofence: bool
    is_native: bool
    clock_out_confirmed: bool = False
    device_challenge_id: Optional[UUID] = None
    device_signature: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    gps_accuracy_meters: Optional[float] = None


class SubmitClockPunchUseCase(BaseUseCase[ClockAttendanceOutputDTO]):
    """Clock in/out. A missing or unapproved device proof does not block the punch; it flags it for review."""

    def __init__(
        self,
        clock: ClockAttendanceUseCase,
        proofs: DeviceProofService,
        refresher: RecentAttendanceRefresher,
        audit: AuditTrail,
    ):
        self._clock = clock
        self._proofs = proofs
        self._refresher = refresher
        self._audit = audit

    async def _prove_device(self, data: SubmitClockPunchInput) -> Optional[dict[str, str]]:
        if data.device_challenge_id is None or data.device_signature is None:
            logger.warning(
                "Attendance submitted without approved browser proof; supervisor review is required.",
                extra={"user_id": str(data.user_id)},
            )
            return None
        try:
            return await self._proofs.consume(
                data.user_id, data.device_challenge_id, "CLOCK", data.device_signature
            )
        except ValueError as error:
            logger.warning(
                "Attendance browser proof was not approved; supervisor review is required: %s",
                error,
                extra={"user_id": str(data.user_id)},
            )
            return None

    async def _execute(self, data: SubmitClockPunchInput) -> ClockAttendanceOutputDTO:
        device_proof = await self._prove_device(data)
        clock_channel = dict(data.clock_channel)
        if device_proof is not None:
            clock_channel.update(
                {"device_id": device_proof["device_id"], "device_uuid": device_proof["device_uuid"]}
            )
        result = await self._clock.execute(
            ClockAttendanceInputDTO(
                image_bytes=data.image_bytes,
                user_id=data.user_id,
                clock_out_confirmed=data.clock_out_confirmed,
                device_approved=device_proof is not None,
                enforce_geofence=data.enforce_geofence,
                allow_wfh=bool(
                    data.is_native
                    and device_proof
                    and device_proof.get("platform") in NATIVE_PLATFORMS
                ),
                clock_channel=clock_channel,
                punch_metadata={"device_proof": device_proof} if device_proof else None,
                latitude=data.latitude,
                longitude=data.longitude,
                gps_accuracy_meters=data.gps_accuracy_meters,
            )
        )
        self._refresher.request_refresh(data.user_id)
        await self._audit.record(
            user_id=SYSTEM_ACTOR,
            action="CREATE",
            resource="attendance",
            resource_id=result.employee_code,
            after=result,
        )
        return result


@dataclass
class SubmitBreakPunchInput:
    user_id: UUID
    break_type: str
    image_bytes: bytes
    device_challenge_id: UUID
    device_signature: str
    punch_metadata: dict[str, Any]


class SubmitBreakPunchUseCase(BaseUseCase[RecordBreakOutputDTO]):
    """Breaks, unlike clock punches, require an approved device proof."""

    def __init__(
        self,
        record_break: RecordBreakUseCase,
        proofs: DeviceProofService,
        refresher: RecentAttendanceRefresher,
        audit: AuditTrail,
    ):
        self._record_break = record_break
        self._proofs = proofs
        self._refresher = refresher
        self._audit = audit

    async def _execute(self, data: SubmitBreakPunchInput) -> RecordBreakOutputDTO:
        device_proof = await self._proofs.consume(
            data.user_id, data.device_challenge_id, "BREAK", data.device_signature
        )
        result = await self._record_break.execute(
            RecordBreakInputDTO(
                break_type=data.break_type,
                user_id=data.user_id,
                image_bytes=data.image_bytes,
                device_proof=device_proof,
                punch_metadata=data.punch_metadata,
            )
        )
        self._refresher.request_refresh(data.user_id)
        await self._audit.record(
            user_id=SYSTEM_ACTOR,
            action="CREATE",
            resource="attendance_break",
            resource_id=result.employee_code,
            after=result,
        )
        return result
