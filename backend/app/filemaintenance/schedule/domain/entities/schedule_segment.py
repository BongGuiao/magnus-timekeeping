from dataclasses import dataclass
from datetime import time
from typing import Literal
from uuid import UUID


ScheduleSegmentType = Literal["WORK", "PAID_BREAK", "UNPAID_BREAK"]


@dataclass
class ScheduleSegmentEntity:
    schedule_template_id: UUID
    segment_sequence: int
    segment_type: ScheduleSegmentType
    start_time: time
    end_time: time
    end_day_offset: int = 0
    paid_minutes: int = 0
    punch_required: bool = False
    auto_deduct: bool = False
    flex_start_minutes: int = 0
    break_slot: Literal["FIRST_BREAK", "MEAL_BREAK", "SECOND_BREAK"] | None = None
    work_segment_sequence: int | None = None
    break_minutes: int = 0
    id: UUID | None = None
