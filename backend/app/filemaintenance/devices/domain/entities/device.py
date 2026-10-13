from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

RegistrationStatus = Literal["PENDING", "APPROVED", "REJECTED", "REVOKED"]


@dataclass
class DeviceEntity:
    device_uuid: str
    platform: str
    device_name: str | None = None
    enrollment_ip: str | None = None
    employee_id: UUID | None = None
    manufacturer: str | None = None
    model: str | None = None
    os_version: str | None = None
    app_version: str | None = None
    registration_status: RegistrationStatus = "PENDING"
    is_rooted_or_jailbroken: bool | None = None
    registered_at: datetime | None = None
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: UUID | None = None
    revocation_reason: str | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None
    is_active: bool = True
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None
