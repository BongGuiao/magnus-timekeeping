from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass
class PayrollCutoffEntity:
    payroll_group_id: UUID
    cutoff_code: str
    period_start: date
    period_end: date
    pay_date: date
    cutoff_half: str | None = None
    attendance_deadline: datetime | None = None
    status: str = "SCHEDULED"
    locked_at: datetime | None = None
    locked_by: UUID | None = None
    attendance_finalized_at: datetime | None = None
    attendance_finalized_by: UUID | None = None
    calculation_version: str | None = None
    export_batch_id: UUID | None = None
    created_at: datetime | None = None
    created_by: UUID | None = None
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    row_version: int | None = None
    is_active: bool = True
    id: UUID | None = None
