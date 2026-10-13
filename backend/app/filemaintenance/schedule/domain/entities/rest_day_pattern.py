from dataclasses import dataclass
from uuid import UUID


@dataclass
class RestDayPatternDayEntity:
    pattern_id: UUID
    cycle_day_no: int
    is_workday: bool
    schedule_template_id: UUID | None = None


@dataclass
class RestDayPatternEntity:
    pattern_code: str
    pattern_name: str
    cycle_length_days: int
    description: str | None
    is_active: bool
    days: list[RestDayPatternDayEntity]
    id: UUID | None = None
