import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from cryptography.exceptions import InvalidKey, InvalidSignature
from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.infrastructure.kiosk_models import KioskChallengeModel, KioskDeviceModel
from app.auth.infrastructure.db_model import UserModel
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel
from app.filemaintenance.devices.application.device_proof import _jwk_public_key, verify_device_signature
from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel, EmploymentAssignmentModel, EmploymentAssignmentLocationModel,
)
from app.filemaintenance.location.infrastructure.db_model import Location

logger = logging.getLogger(__name__)


def payload_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def clock_payload(user_id: UUID, action: str, image: bytes) -> str:
    return f"{user_id}\n{action}\n{hashlib.sha256(image).hexdigest()}"


def validate_challenge(challenge: KioskChallengeModel, purpose: str, payload: str, now: datetime) -> None:
    if challenge.consumed_at is not None or challenge.expires_at <= now:
        raise HTTPException(403, "Kiosk proof has expired or was already used. Please try again.")
    if challenge.purpose != purpose or challenge.payload_hash != payload_hash(payload):
        raise HTTPException(403, "Kiosk proof does not match this request.")


async def require_active_location(session: AsyncSession, company_id: UUID, location_id: UUID) -> None:
    location = await session.scalar(
        select(Location.id).join(CompanyModel, CompanyModel.id == Location.company_id).where(
            Location.id == location_id, Location.company_id == company_id,
            Location.is_active.is_(True), Location.deleted_at.is_(None),
            Location.status == "ACTIVE",
            CompanyModel.is_active.is_(True), CompanyModel.status == "ACTIVE",
        )
    )
    if location is None:
        raise HTTPException(403, "The kiosk company or location is inactive or invalid.")


async def scoped_employee(
    session: AsyncSession, device: KioskDeviceModel, *, code: str | None = None, user_id: UUID | None = None,
) -> tuple[UserModel, EmployeeModel]:
    today = datetime.now(ZoneInfo("Asia/Manila")).date()
    assignment_location = select(EmploymentAssignmentLocationModel.assignment_id).where(
        EmploymentAssignmentLocationModel.location_id == device.location_id,
        EmploymentAssignmentLocationModel.company_id == device.company_id,
    )
    query = (
        select(UserModel, EmployeeModel)
        .join(EmployeeModel, EmployeeModel.id == UserModel.employee_id)
        .join(EmploymentAssignmentModel, EmploymentAssignmentModel.employee_id == EmployeeModel.id)
        .where(
            UserModel.is_active.is_(True), UserModel.account_status == "ACTIVE",
            EmployeeModel.is_active.is_(True),
            EmployeeModel.record_status == "ACTIVE",
            EmploymentAssignmentModel.company_id == device.company_id,
            EmploymentAssignmentModel.is_active.is_(True),
            EmploymentAssignmentModel.status == "ACTIVE",
            EmploymentAssignmentModel.effective_from <= today,
            or_(EmploymentAssignmentModel.effective_to.is_(None), EmploymentAssignmentModel.effective_to >= today),
            or_(EmploymentAssignmentModel.separation_date.is_(None), EmploymentAssignmentModel.separation_date >= today),
            or_(
                EmploymentAssignmentModel.primary_location_id == device.location_id,
                EmploymentAssignmentModel.id.in_(assignment_location),
            ),
        )
    )
    query = query.where(EmployeeModel.employee_no == code) if code is not None else query.where(UserModel.id == user_id)
    row = (await session.execute(query)).first()
    if row is None:
        raise HTTPException(403, "Employee is inactive or is not assigned to this kiosk's company and location.")
    return row[0], row[1]


async def current_user_company(session: AsyncSession, user_id: UUID) -> CompanyModel:
    today = datetime.now(ZoneInfo("Asia/Manila")).date()
    companies = (await session.scalars(
        select(CompanyModel)
        .join(EmploymentAssignmentModel, EmploymentAssignmentModel.company_id == CompanyModel.id)
        .join(EmployeeModel, EmployeeModel.id == EmploymentAssignmentModel.employee_id)
        .join(UserModel, UserModel.employee_id == EmployeeModel.id)
        .where(
            UserModel.id == user_id, UserModel.is_active.is_(True), UserModel.account_status == "ACTIVE",
            EmployeeModel.is_active.is_(True), EmployeeModel.record_status == "ACTIVE",
            EmploymentAssignmentModel.is_active.is_(True), EmploymentAssignmentModel.status == "ACTIVE",
            EmploymentAssignmentModel.effective_from <= today,
            or_(EmploymentAssignmentModel.effective_to.is_(None), EmploymentAssignmentModel.effective_to >= today),
            or_(EmploymentAssignmentModel.separation_date.is_(None), EmploymentAssignmentModel.separation_date >= today),
            CompanyModel.is_active.is_(True), CompanyModel.status == "ACTIVE",
        ).distinct()
    )).all()
    if len(companies) != 1:
        raise HTTPException(
            409,
            "Kiosk management requires exactly one active company in your current employment assignments. "
            "Contact HR to correct your assignment.",
        )
    return companies[0]


class KioskService:
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def enroll(self, device_id: UUID, name: str, jwk: dict) -> dict:
        try:
            _jwk_public_key(jwk)
        except (InvalidKey, KeyError, TypeError, ValueError) as error:
            raise HTTPException(422, "A valid public ECDSA P-256 key is required.") from error
        now = datetime.now(timezone.utc)
        async with self.uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            device = await session.get(KioskDeviceModel, device_id, with_for_update=True)
            if device is None:
                device = KioskDeviceModel(
                    id=device_id, device_name=name, public_key_jwk=jwk, status="PENDING",
                    pairing_code=secrets.token_hex(8).upper(), pairing_expires_at=now + timedelta(minutes=15),
                )
                session.add(device)
            elif _jwk_public_key(device.public_key_jwk).public_numbers() != _jwk_public_key(jwk).public_numbers():
                raise HTTPException(403, "This kiosk identifier already has a different key.")
            elif device.status == "PENDING" and device.pairing_expires_at <= now:
                device.pairing_code = secrets.token_hex(8).upper()
                device.pairing_expires_at = now + timedelta(minutes=15)
            # Pairing codes are returned only for pending devices, never for approved stations.
            return {
                "device_id": str(device.id), "status": device.status,
                "pairing_code": device.pairing_code if device.status == "PENDING" else None,
                "pairing_expires_at": device.pairing_expires_at.isoformat(),
            }

    async def challenge(self, device_id: UUID, purpose: str, digest: str) -> dict:
        now = datetime.now(timezone.utc)
        async with self.uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            device = await session.get(KioskDeviceModel, device_id, with_for_update=True)
            if device is None or device.status == "REVOKED":
                raise HTTPException(403, "Device not registered or kiosk authorization revoked.")
            if purpose != "STATUS" and device.status != "APPROVED":
                raise HTTPException(403, "Device not registered. Administrator approval is required.")
            await session.execute(delete(KioskChallengeModel).where(KioskChallengeModel.expires_at < now))
            outstanding = await session.scalar(
                select(func.count()).select_from(KioskChallengeModel).where(
                    KioskChallengeModel.device_id == device_id,
                    KioskChallengeModel.consumed_at.is_(None),
                )
            )
            if outstanding is not None and outstanding >= 30:
                raise HTTPException(429, "Too many outstanding kiosk requests. Please wait 90 seconds.")
            challenge_id = uuid4()
            expires = now + timedelta(seconds=90)
            message = (
                f"magnus-kiosk-v1\n{challenge_id}\n{device_id}\n{purpose}\n{digest}\n"
                f"{int(expires.timestamp())}\n{secrets.token_urlsafe(24)}"
            )
            session.add(KioskChallengeModel(
                id=challenge_id, device_id=device_id, purpose=purpose, payload_hash=digest,
                message=message, expires_at=expires,
            ))
            return {"challenge_id": str(challenge_id), "message": message}

    async def authorize(self, challenge_id: UUID, signature: str, purpose: str, payload: str) -> KioskDeviceModel:
        now = datetime.now(timezone.utc)
        invalid_signature = False
        async with self.uow as uow:
            session = uow.session
            if session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            challenge = await session.get(KioskChallengeModel, challenge_id)
            if challenge is None:
                raise HTTPException(403, "Kiosk proof was not found.")
            # Use the same device-then-challenge lock order as challenge issuance.
            device = await session.get(KioskDeviceModel, challenge.device_id, with_for_update=True)
            if device is None or device.status == "REVOKED" or (purpose != "STATUS" and device.status != "APPROVED"):
                raise HTTPException(403, "Kiosk is not approved or has been revoked.")
            challenge = await session.get(
                KioskChallengeModel, challenge_id, with_for_update=True, populate_existing=True,
            )
            if challenge is None:
                raise HTTPException(403, "Kiosk proof was not found.")
            now = datetime.now(timezone.utc)
            validate_challenge(challenge, purpose, payload, now)
            try:
                verify_device_signature(device.public_key_jwk, challenge.message.encode(), signature)
            except (InvalidKey, InvalidSignature, KeyError, TypeError, ValueError):
                logger.warning("Rejected kiosk signature for device %s", device.id)
                invalid_signature = True
            challenge.consumed_at = now
            if not invalid_signature:
                if device.status == "APPROVED":
                    if device.company_id is None or device.location_id is None:
                        raise HTTPException(403, "Kiosk company and location have not been configured.")
                    await require_active_location(session, device.company_id, device.location_id)
                device.last_seen_at = now
        if invalid_signature:
            raise HTTPException(403, "Invalid kiosk device signature.")
        return device

    async def employee(
        self, device: KioskDeviceModel, *, code: str | None = None, user_id: UUID | None = None,
    ) -> tuple[UserModel, EmployeeModel]:
        async with self.uow as uow:
            if uow.session is None:
                raise RuntimeError("UnitOfWork session is not active.")
            return await scoped_employee(uow.session, device, code=code, user_id=user_id)
