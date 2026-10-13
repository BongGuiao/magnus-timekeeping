from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Any
from decimal import Decimal
from uuid import UUID

@dataclass
class AttendanceEntity:
    user_id: UUID
    work_date: date
    
    id: Optional[UUID] = None

    # --- Shift Snapshot ---
    shift_id: Optional[int] = None
    schedule_template_id: Optional[UUID] = None
    expected_clock_in_at: Optional[datetime] = None
    expected_clock_out_at: Optional[datetime] = None
    
    # --- Raw Machine Punches ---
    clock_in_at: Optional[datetime] = None
    clock_out_at: Optional[datetime] = None

    # --- Corrected Punches ---
    corrected_clock_in_at: Optional[datetime] = None
    corrected_clock_out_at: Optional[datetime] = None
    
    # --- Short Rest Breaks ---
    first_break_out_at: Optional[datetime] = None
    first_break_in_at: Optional[datetime] = None
    
    second_break_out_at: Optional[datetime] = None
    second_break_in_at: Optional[datetime] = None

    # --- Main Meal / Lunch Break ---
    meal_break_out_at: Optional[datetime] = None
    meal_break_in_at: Optional[datetime] = None
    
    # --- Overtime Dinner Break ---
    ot_break_out_at: Optional[datetime] = None
    ot_break_in_at: Optional[datetime] = None

    # --- Day Classification ---
    work_type: str = "REG"
    day_type: str = "REG"

    # --- Leaves & Absences ---
    is_absent: bool = False
    leave_type: Optional[str] = None
    paid_leave_hours: Optional[float] = None

    # --- Workflow & Approvals ---
    record_status: str = "VALID"
    correction_reason: Optional[str] = None
    related_ticket_jo: Optional[str] = None
    approved_by_id: Optional[UUID] = None
    approved_at: Optional[datetime] = None

    # --- Payroll Computations & Flags ---
    is_manual_entry: bool = False
    auto_meal_deduct_applied: bool = False
    is_early_out_approved: bool = False
    is_locked: bool = False
    late_minutes: int = 0
    undertime_minutes: int = 0
    calculated_ot_minutes: int = 0
    overtime_hours: Decimal = Decimal("0")
    regular_overtime_minutes: int = 0
    regular_overtime_hours: Decimal = Decimal("0")
    night_differential_overtime_minutes: int = 0
    night_differential_overtime_hours: Decimal = Decimal("0")
    night_differential_minutes: int = 0
    night_differential_hours: Decimal = Decimal("0")
    overtime_request_status: Optional[str] = None
    requested_regular_overtime_minutes: int = 0
    requested_night_differential_overtime_minutes: int = 0
    requested_night_differential_minutes: int = 0
    overtime_requested_at: Optional[datetime] = None
    approved_regular_overtime_minutes: int = 0
    approved_night_differential_overtime_minutes: int = 0
    approved_night_differential_minutes: int = 0
    overtime_approved_by_id: Optional[UUID] = None
    overtime_approved_at: Optional[datetime] = None

    # --- FINAL PAYROLL BASIS ---
    approved_hours_worked: Optional[float] = None
    
    approved_ot_start_at: Optional[datetime] = None
    approved_ot_end_at: Optional[datetime] = None
    approved_ot_worked: Optional[float] = None
    
    approved_night_diff: Optional[float] = None

    # --- Audit Trail & Geofencing ---
    punch_metadata: Optional[Dict[str, Any]] = field(default_factory=dict)
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # ==========================================
    # COMPUTED PROPERTIES
    # ==========================================
    
    def _calc_hours(self, start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
        if start and end:
            return round((end - start).total_seconds() / 3600.0, 2)
        return None

    @property
    def effective_clock_in(self) -> Optional[datetime]:
        return self.corrected_clock_in_at or self.clock_in_at

    @property
    def effective_clock_out(self) -> Optional[datetime]:
        return self.corrected_clock_out_at or self.clock_out_at

    @property
    def gross_clocked_hours(self) -> Optional[float]:
        return self._calc_hours(self.effective_clock_in, self.effective_clock_out)
        
    @property
    def first_break_hours(self) -> Optional[float]:
        return self._calc_hours(self.first_break_out_at, self.first_break_in_at)

    @property
    def second_break_hours(self) -> Optional[float]:
        return self._calc_hours(self.second_break_out_at, self.second_break_in_at)

    @property
    def meal_break_hours(self) -> Optional[float]:
        return self._calc_hours(self.meal_break_out_at, self.meal_break_in_at)

    @property
    def ot_break_hours(self) -> Optional[float]:
        return self._calc_hours(self.ot_break_out_at, self.ot_break_in_at)