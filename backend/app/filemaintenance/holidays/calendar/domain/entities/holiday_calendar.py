from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass
class HolidayCalendarEntity:
    company_id: UUID
    calendar_code: str
    calendar_name: str
    effective_year: int
    status: Literal["DRAFT", "PUBLISHED", "CLOSED"] = "DRAFT"
    created_by: UUID | None = None
    updated_by: UUID | None = None
    is_active: bool = True
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None
