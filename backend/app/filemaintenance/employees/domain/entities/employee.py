from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID


@dataclass
class EmployeeEntity:
    employee_no: str
    first_name: str
    last_name: str
    middle_name: str | None = None
    suffix: str | None = None
    preferred_name: str | None = None
    birth_date: date | None = None
    gender_code: str | None = None
    personal_email: str | None = None
    mobile_no: str | None = None
    photo_reference: str | None = None
    record_status: Literal["ACTIVE", "ARCHIVED"] = "ACTIVE"
    created_by: UUID | None = None
    updated_by: UUID | None = None
    is_active: bool = True
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None
