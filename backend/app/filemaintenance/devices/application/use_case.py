from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from app.core.generics.mapper import GenericMapper
from app.core.generics.uc_base import BaseUseCase
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.devices.domain.entities.device import DeviceEntity
from app.filemaintenance.devices.infrastructure.db_model import DeviceCredentialModel, DeviceModel
from app.filemaintenance.employees.infrastructure.db_model import EmployeeModel

REGISTRATION_STATUSES = {"PENDING", "APPROVED", "REJECTED", "REVOKED"}
CREATE_STATUSES = {"PENDING"}
# Lifecycle timestamps/actors are owned by the use case, never by the client payload.
SYSTEM_FIELDS = ("registered_at", "revoked_at", "revoked_by", "created_at", "updated_at", "row_version")
MAX_LENGTHS = {
    "device_uuid": 200,
    "device_name": 100,
    "enrollment_ip": 45,
    "platform": 30,
    "manufacturer": 100,
    "model": 100,
    "os_version": 50,
    "app_version": 50,
}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: value for key, value in payload.items() if key not in SYSTEM_FIELDS}
    for field in ("employee_id", "created_by", "updated_by", "id"):
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = UUID(value) if value.strip() else None
    for field, max_length in MAX_LENGTHS.items():
        if field in normalized:
            value = _clean_text(normalized[field])
            if value is not None and len(value) > max_length:
                raise ValueError(f"{field} must be at most {max_length} characters.")
            normalized[field] = value
    if normalized.get("platform"):
        normalized["platform"] = normalized["platform"].upper()
    if "registration_status" in normalized:
        status = (_clean_text(normalized["registration_status"]) or "").upper()
        if status not in REGISTRATION_STATUSES:
            raise ValueError(f"registration_status must be one of {sorted(REGISTRATION_STATUSES)}.")
        normalized["registration_status"] = status
    if "revocation_reason" in normalized:
        normalized["revocation_reason"] = _clean_text(normalized["revocation_reason"])
    return normalized


async def _ensure_employee_exists(uow: GenUnitOfWork, employee_id: UUID | None) -> None:
    if employee_id is None:
        return
    if uow.session is None:
        raise RuntimeError("UnitOfWork session is not active.")
    exists = await uow.session.scalar(select(EmployeeModel.id).where(EmployeeModel.id == employee_id))
    if exists is None:
        raise ValueError("Employee not found.")


async def _identity_user_or_none(uow: GenUnitOfWork, actor_id: UUID | None) -> UUID | None:
    # revoked_by has an FK to identity.users; drop actor ids that are not (or no longer) user accounts.
    if actor_id is None or uow.session is None:
        return None
    exists = await uow.session.scalar(
        text("SELECT 1 FROM identity.users WHERE id = :user_id"),
        {"user_id": actor_id},
    )
    return actor_id if exists else None


class CreateDeviceUseCase(BaseUseCase[DeviceEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, payload: dict[str, Any]) -> DeviceEntity:
        data = _normalize_payload(payload)
        data.pop("id", None)
        if not data.get("device_uuid"):
            raise ValueError("device_uuid is required.")
        if not data.get("platform"):
            raise ValueError("platform is required.")
        status = data.setdefault("registration_status", "PENDING")
        if status not in CREATE_STATUSES:
            raise ValueError("New devices must be registered as PENDING and approved after key enrollment.")
        data["revocation_reason"] = None
        if status == "APPROVED":
            data["registered_at"] = datetime.now(timezone.utc)

        async with self.uow as uow:
            repo = uow.get_repo(DeviceEntity, DeviceModel)
            if await repo.find_one(DeviceModel.device_uuid == data["device_uuid"]):
                raise ValueError("This device is already registered.")
            await _ensure_employee_exists(uow, data.get("employee_id"))
            return await repo.add(data)


class GetDeviceUseCase(BaseUseCase[DeviceEntity | None]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(self, device_id: UUID) -> DeviceEntity | None:
        async with self.uow as uow:
            repo = uow.get_repo(DeviceEntity, DeviceModel)
            return await repo.find_one(DeviceModel.id == device_id)


class ListDevicesUseCase(BaseUseCase[list[DeviceEntity]]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        employee_id: UUID | None = None,
        registration_status: str | None = None,
        platform: str | None = None,
        is_active: bool | None = None,
    ) -> list[DeviceEntity]:
        async with self.uow as uow:
            repo = uow.get_repo(DeviceEntity, DeviceModel)
            criteria = []
            if employee_id is not None:
                criteria.append(DeviceModel.employee_id == employee_id)
            if registration_status:
                criteria.append(DeviceModel.registration_status == registration_status.strip().upper())
            if platform:
                criteria.append(DeviceModel.platform == platform.strip().upper())
            if is_active is not None:
                criteria.append(DeviceModel.is_active.is_(is_active))
            return await repo.find_all(
                *criteria,
                order_by=(DeviceModel.created_at.desc(), DeviceModel.device_uuid),
                offset=0,
                limit=1000,
            )


class UpdateDeviceUseCase(BaseUseCase[DeviceEntity]):
    def __init__(self, uow: GenUnitOfWork):
        self.uow = uow

    async def _execute(
        self,
        device_id: UUID,
        payload: dict[str, Any],
        actor_id: UUID | None = None,
    ) -> DeviceEntity:
        data = _normalize_payload(payload)
        data.pop("id", None)
        async with self.uow as uow:
            repo = uow.get_repo(DeviceEntity, DeviceModel)
            existing = await repo.find_one(DeviceModel.id == device_id)
            if existing is None:
                raise ValueError("Device not found.")

            if "device_uuid" in data and data["device_uuid"] != existing.device_uuid:
                raise ValueError("device_uuid cannot be changed. Register the new device instead.")
            if "platform" in data and not data["platform"]:
                raise ValueError("platform is required.")
            if "employee_id" in data and data["employee_id"] != existing.employee_id:
                await _ensure_employee_exists(uow, data["employee_id"])

            entity_data = GenericMapper.to_entity({**existing.__dict__, **data}, DeviceEntity)
            changes = {
                key: value
                for key, value in entity_data.__dict__.items()
                if key not in ("id", "created_by", "updated_by", *SYSTEM_FIELDS)
            }

            new_status = changes["registration_status"]
            if new_status == "APPROVED":
                session = uow.session
                if session is None:
                    raise RuntimeError("UnitOfWork session is not active.")
                has_credential = await session.scalar(
                    select(DeviceCredentialModel.device_id).where(
                        DeviceCredentialModel.device_id == device_id
                    )
                )
                if has_credential is None:
                    raise ValueError("A device must have an enrolled public key before it can be approved.")
            now_utc = datetime.now(timezone.utc)
            lifecycle: dict[str, Any] = {
                "registered_at": existing.registered_at,
                "revoked_at": existing.revoked_at,
                "revoked_by": existing.revoked_by,
            }
            if new_status != existing.registration_status:
                if new_status == "APPROVED":
                    lifecycle["registered_at"] = now_utc
                elif new_status in ("PENDING", "REJECTED"):
                    lifecycle["registered_at"] = None
                if new_status == "REVOKED":
                    lifecycle["revoked_at"] = now_utc
                    lifecycle["revoked_by"] = await _identity_user_or_none(uow, actor_id)
                else:
                    lifecycle["revoked_at"] = None
                    lifecycle["revoked_by"] = None
            if new_status == "REVOKED":
                if not changes.get("revocation_reason"):
                    raise ValueError("revocation_reason is required when revoking a device.")
            else:
                changes["revocation_reason"] = None

            updated = replace(
                existing,
                **changes,
                **lifecycle,
                updated_by=data.get("updated_by") or existing.updated_by,
            )
            return await repo.update(updated)
