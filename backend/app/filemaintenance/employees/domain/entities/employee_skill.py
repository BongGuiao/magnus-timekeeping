from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass
class EmployeeSkillEntity:
    employee_id: UUID
    skill_code: str
    proficiency_level: str | None = None
    certification_no: str | None = None
    issued_date: date | None = None
    expiry_date: date | None = None
    verified_by: UUID | None = None
    status: str = "VALID"
    created_by: UUID | None = None
    updated_by: UUID | None = None
    is_active: bool = True
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None
