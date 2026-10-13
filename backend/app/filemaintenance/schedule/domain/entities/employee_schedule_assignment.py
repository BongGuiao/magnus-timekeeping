from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass
class EmployeeScheduleAssignmentEntity:
    employee_id: UUID
    schedule_template_id: UUID
    assignment_type: str
    effective_from: date
    rest_day_pattern_id: UUID | None = None
    effective_to: date | None = None
    reason: str | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    status: str = "DRAFT"
    created_at: datetime | None = None
    created_by: UUID | None = None
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    row_version: int | None = None
    is_active: bool = True
    id: UUID | None = None
