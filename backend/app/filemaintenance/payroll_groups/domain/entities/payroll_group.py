from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID


@dataclass
class PayrollGroupEntity:
    company_id: UUID
    payroll_group_code: str
    payroll_group_name: str
    pay_frequency: Literal["WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY"]
    rate_type: Literal["MONTHLY", "DAILY", "HOURLY"]
    standard_minutes_per_day: int = 480
    annual_divisor: Decimal | None = None
    rounding_minutes: int = 1
    holiday_calendar_id: UUID | None = None
    status: str = "ACTIVE"
    created_by: UUID | None = None
    updated_by: UUID | None = None
    is_active: bool = True
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None
