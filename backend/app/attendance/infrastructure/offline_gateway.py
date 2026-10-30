import base64
import hashlib
import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.exceptions import InvalidSignature
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.application.use_case import (
    ClockAttendanceInputDTO, ClockAttendanceUseCase, GetLastAttendanceInputDTO,
    GetLastAttendanceUseCase, RecordBreakInputDTO, RecordBreakUseCase,
    get_last_punch_time, lock_attendance_user,
)
from app.attendance.domain.authorized_sites import build_authorized_sites
from app.attendance.domain.offline import (
    OFFLINE_LIFETIME, circle_contains, event_message, fingerprint,
    parse_instant, validate_capture,
)
from app.attendance.infrastructure.authorized_location_repository import SqlAlchemyAuthorizedLocationRepository
from app.attendance.infrastructure.db_model import AttendanceModel
from app.attendance.infrastructure.offline_models import OfflinePermitModel, OfflinePunchEventModel
from app.auth.infrastructure.db_model import UserModel
from app.core.config import settings
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.devices.application.device_proof import _decode_base64url, _jwk_public_key
from app.filemaintenance.devices.infrastructure.db_model import DeviceCredentialModel, DeviceModel
from app.filemaintenance.employees.infrastructure.db_model import EmploymentAssignmentModel
from app.filemaintenance.geofences.infrastructure.db_model import Geofence
from app.filemaintenance.payroll_cutoffs.infrastructure.db_model import PayrollCutoffModel
from app.filemaintenance.payroll_cutoffs.infrastructure.employee_cutoff_result_db_model import EmployeeCutoffResultModel

logger = logging.getLogger(__name__)
PH = ZoneInfo("Asia/Manila")


def snapshot_json(value: dict) -> dict:
    return json.loads(json.dumps(
        value, default=lambda item: item.isoformat() if isinstance(item, (datetime, date)) else str(item),
    ))


class TransactionAttendanceUow(GenUnitOfWork):
    """Keep the existing attendance use cases inside the ingestion transaction."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._repo_cache = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


def photo_cipher() -> Fernet:
    key = hashlib.sha256(("magnus-offline-photo-v1:" + settings.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def event_result(event: OfflinePunchEventModel) -> dict:
    return {
        "event_id": str(event.id), "status": event.status, "reason": event.reason,
        "captured_at": event.captured_at.isoformat(),
        "received_at": event.received_at.isoformat(),
        "attendance_id": str(event.attendance_id) if event.attendance_id else None,
    }


class SqlAlchemyOfflineAttendanceGateway:
    def __init__(self, uow: GenUnitOfWork, face_service):
        self._uow = uow
        self._face_service = face_service

    async def _device(
        self, session: AsyncSession, user_id: UUID, device_uuid: str,
    ) -> tuple[UserModel, DeviceModel, DeviceCredentialModel]:
        row = (await session.execute(
            select(UserModel, DeviceModel, DeviceCredentialModel)
            .join(DeviceModel, DeviceModel.employee_id == UserModel.employee_id)
            .join(DeviceCredentialModel, DeviceCredentialModel.device_id == DeviceModel.id)
            .where(UserModel.id == user_id, DeviceModel.device_uuid == device_uuid)
            .with_for_update(of=DeviceModel)
        )).first()
        if row is None:
            raise ValueError("This device does not belong to the authenticated employee.")
        return row[0], row[1], row[2]

    async def _policy(self, session: AsyncSession, employee_id: UUID, now: datetime) -> list[dict]:
        repo = SqlAlchemyAuthorizedLocationRepository(session)
        locations = await repo.list_assigned_locations(employee_id, now.astimezone(PH).date())
        if not locations:
            return []
        fences = await repo.list_active_geofences(locations, now)
        sites = build_authorized_sites(employee_id, locations, fences, await repo.get_wfh_registration(employee_id))
        polygons = dict((await session.execute(
            select(Geofence.id, func.ST_AsGeoJSON(Geofence.boundary_polygon))
            .where(Geofence.id.in_([fence.id for fence in fences]), Geofence.boundary_polygon.is_not(None))
        )).all())
        result = []
        for site in sites:
            for fence in site.geofences:
                item = snapshot_json(asdict(fence))
                item["location_type"] = site.location_type
                item["polygon"] = json.loads(polygons[fence.geofence_id]) if fence.shape == "POLYGON" else None
                result.append(item)
        return sorted(result, key=lambda value: (value["location_type"], value["geofence_id"]))

    async def _schedules(self, session: AsyncSession, employee_id: UUID, now: datetime) -> dict:
        clock = ClockAttendanceUseCase(TransactionAttendanceUow(session), self._face_service)
        today = now.astimezone(PH).date()
        schedules = {}
        for offset in (-1, 0, 1):
            day = today + timedelta(days=offset)
            schedule = await clock._resolve_schedule_day(clock.uow, employee_id, day)
            schedules[day.isoformat()] = snapshot_json(asdict(schedule))
        return schedules

    async def prepare(self, user_id: UUID, device_uuid: str) -> dict:
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("Offline authorization requires an active transaction.")
            user, device, _ = await self._device(session, user_id, device_uuid)
            if not self._approved(user, device):
                raise ValueError("Offline attendance requires an active, approved Android/iOS device.")
            await lock_attendance_user(session, user_id, user.employee_id)
            now = datetime.now(timezone.utc)
            policy = await self._policy(session, user.employee_id, now)
            if not policy:
                raise ValueError("No active authorized geofence is available for offline attendance.")
            last = await GetLastAttendanceUseCase(TransactionAttendanceUow(session)).execute(
                GetLastAttendanceInputDTO(user_id=user_id),
            )
            permit_id = uuid4()
            snapshot = {
                "permit_id": str(permit_id), "device_uuid": device_uuid, "user_id": str(user_id),
                "issued_at": now.isoformat(), "expires_at": (now + OFFLINE_LIFETIME).isoformat(),
                "geofences": policy,
                "schedules": await self._schedules(session, user.employee_id, now),
                "last_attendance": snapshot_json(asdict(last)) if last else None,
            }
            token = jwt.encode(
                {"aud": "magnus-offline-v1", "permit_id": str(permit_id), "snapshot_hash": fingerprint(snapshot)},
                settings.SECRET_KEY, algorithm=settings.ALGORITHM,
            )
            session.add(OfflinePermitModel(
                id=permit_id, user_id=user_id, device_id=device.id, issued_at=now,
                expires_at=now + OFFLINE_LIFETIME, snapshot=snapshot,
            ))
            return {"snapshot": snapshot, "token": token}

    @staticmethod
    def _approved(user: UserModel, device: DeviceModel) -> bool:
        return (
            user.is_active and user.account_status == "ACTIVE"
            and device.registration_status == "APPROVED" and device.is_active
            and device.revoked_at is None and device.platform in ("ANDROID", "IOS")
        )

    async def ingest(self, user_id: UUID, payload_json: str, signature: str, image: bytes) -> dict:
        payload = json.loads(payload_json)
        if not isinstance(payload, dict) or payload.get("user_id") != str(user_id):
            raise ValueError("Offline event must belong to the authenticated employee.")
        if hashlib.sha256(image).hexdigest() != payload.get("photo_hash"):
            raise ValueError("Offline photo does not match the signed event.")
        async with self._uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("Offline sync requires an active transaction.")
            user, device, credential = await self._device(session, user_id, payload["device_uuid"])
            raw_signature = _decode_base64url(signature)
            if len(raw_signature) != 64:
                raise ValueError("Invalid offline device signature.")
            try:
                _jwk_public_key(credential.public_key_jwk).verify(
                    encode_dss_signature(int.from_bytes(raw_signature[:32], "big"), int.from_bytes(raw_signature[32:], "big")),
                    event_message(payload_json), ec.ECDSA(hashes.SHA256()),
                )
            except InvalidSignature as error:
                raise ValueError("Invalid offline device signature.") from error
            await lock_attendance_user(session, user_id, user.employee_id)
            event_id = UUID(payload["event_id"])
            payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
            existing = await session.get(OfflinePunchEventModel, event_id)
            if existing is not None:
                if existing.user_id != user_id or existing.payload_hash != payload_hash:
                    raise ValueError("Offline event ID was reused with different content.")
                return event_result(existing)
            try:
                claims = jwt.decode(payload["permit_token"], settings.SECRET_KEY,
                                    algorithms=[settings.ALGORITHM], audience="magnus-offline-v1")
            except jwt.PyJWTError as error:
                raise ValueError("Invalid offline authorization signature.") from error
            permit = await session.get(OfflinePermitModel, UUID(claims["permit_id"]))
            if (
                permit is None or permit.user_id != user_id or permit.device_id != device.id
                or claims["snapshot_hash"] != fingerprint(permit.snapshot)
            ):
                raise ValueError("Offline authorization does not belong to this employee and device.")
            received_at = datetime.now(timezone.utc)
            event = OfflinePunchEventModel(
                id=event_id, permit_id=permit.id, user_id=user_id, sequence=payload["sequence"],
                captured_at=parse_instant(payload["captured_at"]), received_at=received_at,
                payload_hash=payload_hash, payload=payload, signature=signature,
                status="NEEDS_REVIEW", encrypted_photo=photo_cipher().encrypt(image),
            )
            reused_sequence = await session.scalar(select(OfflinePunchEventModel.id).where(
                OfflinePunchEventModel.permit_id == permit.id,
                OfflinePunchEventModel.sequence == event.sequence,
            ))
            if reused_sequence:
                raise ValueError("Offline event sequence was reused.")
            session.add(event)
            await session.flush()
            try:
                validate_capture(payload, permit.snapshot, received_at)
            except ValueError as error:
                event.status, event.reason = "REJECTED", str(error)
                event.encrypted_photo = None
                return event_result(event)
            try:
                async with session.begin_nested():
                    await self._apply(session, user, device, permit, event, image)
            except ValueError as error:
                event.status, event.reason = "NEEDS_REVIEW", str(error)
                logger.warning("Offline event %s requires review: %s", event.id, error)
            await session.flush()
            return event_result(event)

    async def _apply(
        self, session: AsyncSession, user: UserModel, device: DeviceModel,
        permit: OfflinePermitModel, event: OfflinePunchEventModel, image: bytes,
    ) -> None:
        payload = event.payload
        if not self._approved(user, device):
            raise ValueError("Employee/device eligibility changed. HR review is required.")
        if payload.get("clock_trusted") is not True:
            raise ValueError("The device clock changed or its time reference was lost. HR review is required.")
        if fingerprint(await self._policy(session, user.employee_id, event.captured_at)) != fingerprint(permit.snapshot["geofences"]):
            raise ValueError("Authorized location rules changed. HR review is required.")
        fences = permit.snapshot["geofences"]
        # PostGIS performs the authoritative polygon and GPS-uncertainty check.
        circle_ok = any(circle_contains(fence, payload["latitude"], payload["longitude"], payload["accuracy"]) for fence in fences)
        if not circle_ok and not any(fence["shape"] == "POLYGON" for fence in fences):
            raise ValueError("The captured GPS reading is outside the authorized boundary.")
        latest = await session.scalar(select(AttendanceModel).where(AttendanceModel.user_id == user.id)
                                      .order_by(AttendanceModel.clock_in_at.desc().nullslast()).limit(1))
        last_punch = get_last_punch_time(latest) if latest else None
        expected = parse_instant(payload["previous_at"]) if payload.get("previous_at") else None
        if last_punch != expected:
            raise ValueError("Another punch changed the attendance sequence. HR review is required.")
        if latest and ((latest.is_locked and payload["action"] != "clock_in") or (last_punch and event.captured_at <= last_punch)):
            raise ValueError("Attendance is locked or the capture time conflicts with existing punches.")
        day = latest.work_date if latest and not latest.clock_out_at and payload["action"] != "clock_in" else event.captured_at.astimezone(PH).date()
        bound = TransactionAttendanceUow(session)
        clock = ClockAttendanceUseCase(bound, self._face_service)
        schedule = await clock._resolve_schedule_day(bound, user.employee_id, day)
        if payload["action"] == "clock_in" and (
            schedule.expected_clock_out_at is None or event.captured_at >= schedule.expected_clock_out_at
        ):
            next_day = day + timedelta(days=1)
            next_schedule = await clock._resolve_schedule_day(bound, user.employee_id, next_day)
            if (
                next_schedule.expected_clock_in_at is not None
                and next_schedule.expected_clock_in_at - timedelta(minutes=next_schedule.early_clock_in_allowance_minutes)
                <= event.captured_at < next_schedule.expected_clock_in_at
            ):
                day, schedule = next_day, next_schedule
        cached_schedule = permit.snapshot["schedules"].get(day.isoformat())
        if cached_schedule != snapshot_json(asdict(schedule)):
            raise ValueError("The work schedule changed or was not cached. HR review is required.")
        cutoffs = (await session.scalars(
            select(PayrollCutoffModel).join(EmploymentAssignmentModel,
                EmploymentAssignmentModel.payroll_group_id == PayrollCutoffModel.payroll_group_id)
            .where(EmploymentAssignmentModel.employee_id == user.employee_id,
                   PayrollCutoffModel.period_start <= day, PayrollCutoffModel.period_end >= day)
            .with_for_update(of=PayrollCutoffModel)
        )).all()
        for cutoff in cutoffs:
            processed = await session.scalar(select(EmployeeCutoffResultModel.id).where(
                EmployeeCutoffResultModel.employee_id == user.employee_id,
                EmployeeCutoffResultModel.cutoff_id == cutoff.id,
            ).limit(1))
            if processed or cutoff.locked_at or cutoff.attendance_finalized_at or cutoff.status not in ("SCHEDULED", "OPEN"):
                raise ValueError("Payroll is locked, finalized, or already processed. HR review is required; payroll was not changed.")
        metadata = {"offline_event_id": str(event.id), "captured_at": event.captured_at.isoformat(),
                    "received_at": event.received_at.isoformat(), "device_uuid": device.device_uuid}
        if payload["action"] in ("clock_in", "clock_out"):
            result = await clock.execute(ClockAttendanceInputDTO(
                user_id=user.id, image_bytes=image, captured_at=event.captured_at,
                requested_action=payload["action"], clock_out_confirmed=payload["action"] == "clock_out",
                device_approved=True, enforce_geofence=True, allow_wfh=True,
                latitude=payload["latitude"], longitude=payload["longitude"], gps_accuracy_meters=payload["accuracy"],
                clock_channel={"channel": "mobile", "offline": True}, punch_metadata=metadata,
            ))
            if result.action != payload["action"]:
                raise ValueError("Offline action conflicts with the active shift.")
        else:
            await clock._validate_clock_in_geofence(
                bound, user, payload["latitude"], payload["longitude"], payload["accuracy"],
                event.captured_at, day, allow_wfh=True,
            )
            await RecordBreakUseCase(bound, self._face_service).execute(RecordBreakInputDTO(
                user_id=user.id, image_bytes=image, captured_at=event.captured_at, break_type=payload["action"],
                device_proof={"device_uuid": device.device_uuid, "offline_event_id": str(event.id)},
                punch_metadata=metadata,
            ))
        await session.flush()
        record = await session.scalar(select(AttendanceModel).where(AttendanceModel.user_id == user.id)
                                      .order_by(AttendanceModel.clock_in_at.desc().nullslast()).limit(1))
        event.attendance_id = record.id if record else None
        event.status, event.reason, event.encrypted_photo = "ACCEPTED", None, None
