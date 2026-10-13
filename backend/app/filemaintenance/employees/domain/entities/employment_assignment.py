from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass
class EmploymentAssignmentEntity:
    employee_id: UUID
    company_id: UUID
    employment_type: str
    employee_category: str
    hire_date: date
    effective_from: date
    org_unit_id: UUID | None = None
    position_id: UUID | None = None
    supervisor_employee_id: UUID | None = None
    operational_group: str | None = None
    payroll_group_id: UUID | None = None
    primary_location_id: UUID | None = None
    effective_to: date | None = None
    separation_date: date | None = None
    status: str = "ACTIVE"
    created_by: UUID | None = None
    updated_by: UUID | None = None
    is_active: bool = True
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None
