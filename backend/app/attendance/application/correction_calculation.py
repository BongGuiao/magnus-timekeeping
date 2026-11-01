from datetime import datetime
from decimal import Decimal
from typing import Any

from app.attendance.application.use_case import (
    calculate_attendance_metrics,
    calculate_break_policy,
    calculate_net_nonpayable_break_minutes,
    calculate_night_differential_minutes,
    calculate_overtime_breakdown,
)
from app.attendance.domain.entities.overtime import OvertimeAttendance


def recalculate_corrected_attendance(
    record: OvertimeAttendance, clock_in: datetime, clock_out: datetime,
) -> dict[str, Any]:
    context = (record.punch_metadata or {}).get("schedule_context") or {}
    if record.expected_clock_in_at is None or record.expected_clock_out_at is None:
        raise ValueError("The attendance record needs valid scheduled start and end times before correction.")
    if record.expected_clock_out_at <= record.expected_clock_in_at or "ot_eligible" not in context:
        raise ValueError("The attendance record needs a valid saved schedule policy before correction.")
    rules = context.get("break_rules") or []
    excess, unpaid, intervals = calculate_break_policy(record, rules, require_complete=False)
    net_break = calculate_net_nonpayable_break_minutes(record, rules, intervals, clock_in, clock_out)
    arguments = dict(
        expected_clock_in_at=record.expected_clock_in_at, expected_clock_out_at=record.expected_clock_out_at,
        actual_clock_in_at=clock_in, actual_clock_out_at=clock_out,
        ot_eligible=bool(context["ot_eligible"]), minimum_ot_minutes=int(context.get("minimum_ot_minutes", 0)),
        pre_shift_ot_allowed=bool(context.get("pre_shift_ot_allowed", False)), break_intervals=intervals,
    )
    regular_ot, night_ot, total_ot = calculate_overtime_breakdown(**arguments)
    late, undertime, _ = calculate_attendance_metrics(**arguments, grace_minutes=int(context.get("grace_minutes", 0)))
    night = calculate_night_differential_minutes(
        actual_clock_in_at=clock_in, actual_clock_out_at=clock_out, break_intervals=intervals,
    )
    metadata = dict(record.punch_metadata or {})
    metadata["break_calculation"] = {
        **(metadata.get("break_calculation") or {}),
        "excess_undertime_minutes": excess, "excess_minutes_break": excess,
        "unpaid_break_minutes": unpaid, "net_nonpayable_minutes": net_break,
        "undertime_excludes_break_excess": True,
    }
    return {
        "late_minutes": late, "undertime_minutes": undertime,
        "calculated_ot_minutes": total_ot, "overtime_hours": Decimal(total_ot) / Decimal(60),
        "regular_overtime_minutes": regular_ot, "regular_overtime_hours": Decimal(regular_ot) / Decimal(60),
        "night_differential_overtime_minutes": night_ot,
        "night_differential_overtime_hours": Decimal(night_ot) / Decimal(60),
        "night_differential_minutes": night, "night_differential_hours": Decimal(night) / Decimal(60),
        "approved_night_differential_minutes": night, "approved_night_diff": night / 60,
        "approved_hours_worked": max(0, int((clock_out - clock_in).total_seconds() // 60) - net_break) / 60,
        "is_absent": False, "punch_metadata": metadata,
    }
