import base64
from datetime import datetime, timedelta, timezone
import secrets
from typing import Literal
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidKey, InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from sqlalchemy import delete, select

from app.auth.infrastructure.db_model import UserModel
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.devices.infrastructure.db_model import (
    DeviceChallengeModel,
    DeviceCredentialModel,
    DeviceModel,
)

ChallengeAction = Literal["CLOCK", "BREAK"]
CHALLENGE_LIFETIME = timedelta(seconds=90)


def _decode_base64url(value: str) -> bytes:
    return base64.b64decode(
        value + "=" * (-len(value) % 4),
        altchars=b"-_",
        validate=True,
    )


def _jwk_public_key(jwk: dict) -> ec.EllipticCurvePublicKey:
    if (
        jwk.get("kty") != "EC"
        or jwk.get("crv") != "P-256"
        or "d" in jwk
        or not isinstance(jwk.get("x"), str)
        or not isinstance(jwk.get("y"), str)
    ):
        raise ValueError("Only ECDSA P-256 device keys are supported.")
    x_bytes = _decode_base64url(jwk["x"])
    y_bytes = _decode_base64url(jwk["y"])
    if len(x_bytes) != 32 or len(y_bytes) != 32:
        raise ValueError("ECDSA P-256 public key coordinates must be 32 bytes.")
    x = int.from_bytes(x_bytes, "big")
    y = int.from_bytes(y_bytes, "big")
    return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()


async def register_attendance_device(
    uow: GenUnitOfWork,
    user_id: UUID,
    device_uuid: str,
    device_name: str,
    public_key_jwk: dict,
    actor_id: UUID,
    manufacturer: str | None = None,
    model: str | None = None,
    os_version: str | None = None,
    app_version: str | None = None,
    platform: str = "WEB",
    enrollment_ip: str | None = None,
) -> dict[str, str]:
    device_uuid = device_uuid.strip()
    if not device_uuid or len(device_uuid) > 200:
        raise ValueError("device_uuid must contain 1 to 200 characters.")
    device_name = device_name.strip()
    if not device_name or len(device_name) > 100:
        raise ValueError("device_name must contain 1 to 100 characters.")
    if not isinstance(public_key_jwk, dict):
        raise ValueError("A public ECDSA P-256 key is required.")
    if len(public_key_jwk) > 8 or len(str(public_key_jwk)) > 2048:
        raise ValueError("The public key JWK is too large.")
    try:
        submitted_key = _jwk_public_key(public_key_jwk).public_numbers()
    except (InvalidKey, KeyError, TypeError, ValueError) as error:
        raise ValueError("The public key must be a valid ECDSA P-256 JWK.") from error

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")
        user = await session.scalar(
            select(UserModel).where(
                UserModel.id == user_id,
                UserModel.is_active.is_(True),
                UserModel.account_status == "ACTIVE",
            )
        )
        if user is None or user.employee_id is None:
            raise ValueError("The employee account is inactive or has no linked employee.")
        existing = (
            await session.execute(
                select(DeviceModel, DeviceCredentialModel)
                .outerjoin(
                    DeviceCredentialModel,
                    DeviceCredentialModel.device_id == DeviceModel.id,
                )
                .where(DeviceModel.device_uuid == device_uuid)
            )
        ).first()
        if existing is not None:
            existing_device, existing_credential = existing
            if existing_device.employee_id != user.employee_id or existing_credential is None:
                raise ValueError(
                    "This device identifier is already registered to another employee or has no valid key."
                )
            try:
                existing_key = _jwk_public_key(existing_credential.public_key_jwk).public_numbers()
            except (InvalidKey, KeyError, TypeError, ValueError) as error:
                raise ValueError("The registered device key is invalid. Contact an administrator.") from error
            if (existing_key.x, existing_key.y) != (submitted_key.x, submitted_key.y):
                raise ValueError(
                    "This device is already registered with a different key. Contact an administrator."
                )
            return {
                "id": str(existing_device.id),
                "device_uuid": device_uuid,
                "registration_status": existing_device.registration_status,
            }

        device_id = uuid4()
        session.add(
            DeviceModel(
                id=device_id,
                device_uuid=device_uuid,
                device_name=device_name,
                enrollment_ip=enrollment_ip,
                employee_id=user.employee_id,
                platform=platform,
                manufacturer=manufacturer,
                model=model,
                os_version=os_version,
                app_version=app_version,
                registration_status="PENDING",
                created_by=actor_id,
                updated_by=actor_id,
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            DeviceCredentialModel(
                device_id=device_id,
                public_key_jwk=public_key_jwk,
            )
        )

    return {
        "id": str(device_id),
        "device_uuid": device_uuid,
        "registration_status": "PENDING",
    }


def challenge_message(
    challenge_id: UUID,
    nonce: str,
    user_id: UUID,
    action: ChallengeAction,
    expires_at: datetime,
) -> str:
    expires_epoch = int(expires_at.timestamp())
    return f"magnus-attendance-device-v1\n{challenge_id}\n{nonce}\n{user_id}\n{action}\n{expires_epoch}"


async def issue_device_challenge(
    uow: GenUnitOfWork,
    user_id: UUID,
    device_uuid: str,
    action: ChallengeAction,
) -> dict[str, str]:
    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")

        user = await session.scalar(
            select(UserModel).where(
                UserModel.id == user_id,
                UserModel.is_active.is_(True),
                UserModel.account_status == "ACTIVE",
            )
        )
        if user is None or user.employee_id is None:
            raise ValueError("The employee account is inactive or has no linked employee.")
        await session.execute(
            delete(DeviceChallengeModel).where(
                (DeviceChallengeModel.expires_at < datetime.now(timezone.utc) - timedelta(days=1))
                | (DeviceChallengeModel.consumed_at < datetime.now(timezone.utc) - timedelta(days=1))
            )
        )

        row = (
            await session.execute(
                select(DeviceModel, DeviceCredentialModel)
                .join(DeviceCredentialModel, DeviceCredentialModel.device_id == DeviceModel.id)
                .where(
                    DeviceModel.device_uuid == device_uuid,
                    DeviceModel.employee_id == user.employee_id,
                    DeviceModel.registration_status == "APPROVED",
                    DeviceModel.is_active.is_(True),
                    DeviceModel.revoked_at.is_(None),
                )
            )
        ).first()
        if row is None:
            raise ValueError("This device is not approved for the selected employee.")

        device, _credential = row
        challenge_id = uuid4()
        nonce = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + CHALLENGE_LIFETIME
        session.add(
            DeviceChallengeModel(
                id=challenge_id,
                device_id=device.id,
                user_id=user_id,
                action=action,
                nonce=nonce,
                expires_at=expires_at,
            )
        )
        message = challenge_message(challenge_id, nonce, user_id, action, expires_at)

    return {
        "challenge_id": str(challenge_id),
        "message": message,
        "expires_at": expires_at.isoformat(),
    }


async def consume_device_challenge(
    uow: GenUnitOfWork,
    user_id: UUID,
    challenge_id: UUID,
    action: ChallengeAction,
    signature: str,
) -> dict[str, str]:
    invalid_signature = False
    device_details: dict[str, str] | None = None
    now = datetime.now(timezone.utc)

    async with uow as active_uow:
        session = active_uow.session
        if session is None:
            raise RuntimeError("UnitOfWork session is not active.")

        challenge = await session.scalar(
            select(DeviceChallengeModel)
            .where(DeviceChallengeModel.id == challenge_id)
            .with_for_update()
        )
        if challenge is None:
            raise ValueError("Device challenge was not found.")
        if challenge.user_id != user_id or challenge.action != action:
            raise ValueError("Device challenge does not match this attendance action.")
        if challenge.consumed_at is not None:
            raise ValueError("Device challenge has already been used.")
        if challenge.expires_at <= now:
            raise ValueError("Device challenge has expired. Please try again.")

        row = (
            await session.execute(
                select(DeviceModel, DeviceCredentialModel)
                .join(DeviceCredentialModel, DeviceCredentialModel.device_id == DeviceModel.id)
                .where(
                    DeviceModel.id == challenge.device_id,
                    DeviceModel.registration_status == "APPROVED",
                    DeviceModel.is_active.is_(True),
                    DeviceModel.revoked_at.is_(None),
                )
            )
        ).first()
        if row is None:
            raise ValueError("This device is not approved or has been revoked.")

        device, credential = row
        user = await session.get(UserModel, user_id)
        if (
            user is None
            or not user.is_active
            or user.account_status != "ACTIVE"
            or user.employee_id is None
            or user.employee_id != device.employee_id
        ):
            raise ValueError("This device is not assigned to the selected employee.")

        message = challenge_message(
            challenge.id,
            challenge.nonce,
            challenge.user_id,
            challenge.action,
            challenge.expires_at,
        ).encode("utf-8")
        try:
            raw_signature = _decode_base64url(signature)
            if len(raw_signature) != 64:
                raise ValueError("Invalid ECDSA signature length.")
            der_signature = encode_dss_signature(
                int.from_bytes(raw_signature[:32], "big"),
                int.from_bytes(raw_signature[32:], "big"),
            )
            _jwk_public_key(credential.public_key_jwk).verify(
                der_signature,
                message,
                ec.ECDSA(hashes.SHA256()),
            )
        except (InvalidKey, InvalidSignature, KeyError, TypeError, ValueError):
            challenge.consumed_at = now
            invalid_signature = True
        else:
            challenge.consumed_at = now
            device.last_seen_at = now
            device_details = {
                "device_id": str(device.id),
                "device_uuid": device.device_uuid,
                "platform": device.platform,
            }

    if invalid_signature:
        raise ValueError("Device signature is invalid. Please retry with this device.")
    if device_details is None:
        raise RuntimeError("Device challenge validation did not produce a result.")
    return device_details
