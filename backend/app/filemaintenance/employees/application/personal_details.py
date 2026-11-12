from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.filemaintenance.employees.infrastructure.db_model import (
    EmployeeModel,
    EmployeePersonalDetailsModel,
)


class EmployeePersonalDetailsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    bank_account_no: str | None = Field(default=None, max_length=100)
    sss_no: str | None = Field(default=None, max_length=30)
    pagibig_no: str | None = Field(default=None, max_length=30)
    philhealth_no: str | None = Field(default=None, max_length=30)
    tin_no: str | None = Field(default=None, max_length=30)
    address_line_1: str | None = Field(default=None, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    region: str | None = Field(default=None, max_length=100)
    psgc_region_code: str | None = Field(default=None, pattern=r"^[0-9]{9}$")
    psgc_province_code: str | None = Field(default=None, pattern=r"^[0-9]{9}$")
    psgc_city_code: str | None = Field(default=None, pattern=r"^[0-9]{9}$")
    psgc_barangay_code: str | None = Field(default=None, pattern=r"^[0-9]{9}$")
    barangay: str | None = Field(default=None, max_length=100)
    city_municipality: str | None = Field(default=None, max_length=100)
    province: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    civil_status: Literal["SINGLE", "MARRIED", "WIDOWED", "SEPARATED", "DIVORCED", "OTHER"] | None = None

    @field_validator("*", mode="before")
    @classmethod
    def normalize_empty(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


def validate_personal_details(payload: object) -> EmployeePersonalDetailsInput:
    try:
        return EmployeePersonalDetailsInput.model_validate(payload)
    except ValidationError as error:
        fields = ", ".join(".".join(str(part) for part in item["loc"]) for item in error.errors())
        raise ValueError(f"Invalid employee personal information: {fields}.") from error


class EmployeePersonalDetailsResponse(EmployeePersonalDetailsInput):
    model_config = ConfigDict(from_attributes=True)

    employee_id: UUID


def plan_personal_details_fill(
    existing: EmployeePersonalDetailsModel | None,
    payload: EmployeePersonalDetailsInput,
) -> tuple[dict[str, str], list[str]]:
    changes: dict[str, str] = {}
    conflicts: list[str] = []
    for field, incoming in payload.model_dump(exclude_unset=True).items():
        if incoming is None:
            continue
        current = getattr(existing, field) if existing is not None else None
        if current is None or (isinstance(current, str) and not current.strip()):
            changes[field] = incoming
        elif current != incoming:
            conflicts.append(field)
    return changes, conflicts


async def save_personal_details(
    session: AsyncSession,
    employee_id: UUID,
    payload: EmployeePersonalDetailsInput,
    actor_id: UUID | None,
) -> None:
    # Lock the parent too: a first-time insert has no details row to lock yet.
    employee = await session.scalar(
        select(EmployeeModel).where(EmployeeModel.id == employee_id).with_for_update()
    )
    if employee is None:
        raise ValueError("Employee not found.")
    record = await session.get(EmployeePersonalDetailsModel, employee_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return
    if record is None:
        if not any(value is not None for value in changes.values()):
            return
        record = EmployeePersonalDetailsModel(employee_id=employee_id, created_by=actor_id)
        session.add(record)
    for field, value in changes.items():
        setattr(record, field, value)
    record.updated_by = actor_id
    record.updated_at = datetime.now(timezone.utc)
    await session.flush()
