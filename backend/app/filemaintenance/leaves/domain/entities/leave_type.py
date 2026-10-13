from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass
class LeaveTypeEntity:
    company_id: UUID
    leave_code: str
    leave_name: str
    leave_category: str
    unit_type: str
    annual_entitlement_minutes: int
    accrual_method: str
    minimum_service_months: int
    allow_negative_balance: bool
    maximum_negative_minutes: int
    carryover_allowed: bool
    maximum_carryover_minutes: int
    expiry_rule: str
    cash_conversion_allowed: bool
    advance_notice_days: int
    document_required: bool
    document_trigger_minutes: int
    exclude_rest_days: bool
    exclude_holidays: bool
    effective_from: date
    effective_to: date | None
    status: str
    created_by: UUID | None = None
    updated_by: UUID | None = None
    is_active: bool = True
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None
