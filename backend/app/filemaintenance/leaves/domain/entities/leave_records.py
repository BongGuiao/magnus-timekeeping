from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass
class EmployeeEntitlementEntity:
    employee_id: UUID
    leave_type_id: UUID
    entitlement_year: int
    opening_minutes: int = 0
    granted_minutes: int = 0
    accrued_minutes: int = 0
    carryover_minutes: int = 0
    adjustment_minutes: int = 0
    used_minutes: int = 0
    reserved_minutes: int = 0
    expired_minutes: int = 0
    converted_minutes: int = 0
    available_minutes: int = 0
    last_calculated_at: datetime | None = None
    id: UUID | None = None


@dataclass
class LeaveApplicationEntity:
    application_no: str
    employee_id: UUID
    leave_type_id: UUID
    start_at: datetime
    end_at: datetime
    duration_type: str
    requested_minutes: int
    reason: str
    paid_minutes: int | None = None
    unpaid_minutes: int | None = None
    contact_information: str | None = None
    reliever_employee_id: UUID | None = None
    is_retroactive: bool = False
    workflow_instance_id: UUID | None = None
    status: str = "DRAFT"
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    cancelled_at: datetime | None = None
    payroll_posted: bool = False
    created_at: datetime | None = None
    created_by: UUID | None = None
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    row_version: int | None = None
    is_active: bool = True
    id: UUID | None = None


@dataclass
class LeaveApplicationDateEntity:
    leave_application_id: UUID
    leave_date: date
    requested_minutes: int
    approved_paid_minutes: int = 0
    approved_unpaid_minutes: int = 0
    holiday_flag: bool = False
    rest_day_flag: bool = False
    attendance_overlap_minutes: int = 0
    final_charge_minutes: int = 0
    roster_id: UUID | None = None
    id: UUID | None = None


@dataclass
class LeaveLedgerEntity:
    employee_id: UUID
    leave_type_id: UUID
    transaction_date: date
    transaction_type: str
    reference_type: str
    minutes_delta: int
    balance_after_minutes: int
    posted_by: UUID
    reference_id: UUID | None = None
    remarks: str | None = None
    posted_at: datetime | None = None
    id: UUID | None = None
