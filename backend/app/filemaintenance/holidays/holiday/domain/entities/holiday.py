from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID


@dataclass
class HolidayEntity:
    holiday_calendar_id: UUID
    holiday_date: date
    holiday_name: str
    holiday_type: Literal[
        "REGULAR",
        "SPECIAL_NONWORKING",
        "SPECIAL_WORKING",
        "LOCAL",
        "COMPANY",
    ]
    region: str | None = None
    province: str | None = None
    city: str | None = None
    psgc_region_code: str | None = None
    psgc_province_code: str | None = None
    psgc_city_code: str | None = None
    ncr_district: str | None = None
    is_double_holiday: bool = False
    pay_rule_code: str | None = None
    source_reference: str | None = None
    status: Literal["ACTIVE", "CANCELLED", "SUPERSEDED"] = "ACTIVE"
    created_by: UUID | None = None
    updated_by: UUID | None = None
    is_active: bool = True
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None
