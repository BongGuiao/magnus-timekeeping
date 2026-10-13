from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID


ScheduleType = Literal[
    "FIXED",
    "FLEXIBLE",
    "SHIFTING",
    "OVERNIGHT",
    "SPLIT",
    "COMPRESSED",
    "FIELD",
    "ON_CALL",
]


@dataclass
class ScheduleTemplateEntity:
    company_id: UUID
    schedule_code: str
    schedule_name: str
    schedule_type: ScheduleType
    required_minutes: int
    grace_minutes: int
    grace_method: str
    is_overnight: bool
    ot_eligible: bool
    pre_shift_ot_allowed: bool
    minimum_ot_minutes: int
    effective_from: date
    effective_to: date | None
    holiday_calendar_id: UUID | None = None
    status: str = "DRAFT"
    created_at: datetime | None = None
    created_by: UUID | None = None
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    row_version: int | None = None
    is_active: bool = True
    id: UUID | None = None
