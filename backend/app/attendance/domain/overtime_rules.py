from datetime import date, datetime
from typing import Iterable, Optional
from uuid import UUID

from app.attendance.domain.entities.overtime import (
    NIGHT_DIFFERENTIAL,
    NIGHT_DIFFERENTIAL_OVERTIME,
    REGULAR_OVERTIME,
    OvertimeApplication,
    OvertimeAttendance,
    OvertimeCutoff,
)
from app.attendance.domain.exceptions import PermissionDeniedError, RuleViolationError

OPEN_APPLICATION_STATUSES = ("PENDING", "APPROVED")

_CATEGORY_FIELDS = {
    REGULAR_OVERTIME: (
        "requested_regular_overtime_minutes",
        "approved_regular_overtime_minutes",
    ),
    NIGHT_DIFFERENTIAL_OVERTIME: (
        "requested_night_differential_overtime_minutes",
        "approved_night_differential_overtime_minutes",
    ),
    NIGHT_DIFFERENTIAL: (
        "requested_night_differential_minutes",
        None,
    ),
}


def validate_cutoff(cutoff: Optional[OvertimeCutoff], work_date: Optional[date] = None) -> OvertimeCutoff:
    if cutoff is None:
        raise RuleViolationError(
            "No current payroll cutoff is configured for your active payroll assignment. Contact HR."
        )
    if work_date is not None and not cutoff.period_start <= work_date <= cutoff.period_end:
        raise RuleViolationError("Overtime attendance must be within your current payroll cutoff.")
    return cutoff


def validate_application_period(
    requested_start_at: datetime,
    requested_end_at: datetime,
    actual_start_at: datetime,
    actual_end_at: datetime,
    requested_minutes: int,
) -> None:
    if actual_end_at <= actual_start_at:
        raise RuleViolationError("The attendance record has no valid completed punch interval.")
    if (
        requested_end_at <= requested_start_at
        or requested_start_at < actual_start_at
        or requested_end_at > actual_end_at
    ):
        raise RuleViolationError(
            "The overtime application period must be within the effective "
            "clock-in and clock-out times on the attendance record."
        )
    period_minutes = int((requested_end_at - requested_start_at).total_seconds() // 60)
    if requested_minutes > period_minutes:
        raise RuleViolationError("Requested minutes cannot exceed the overtime application period.")


def calculated_minutes(attendance: OvertimeAttendance, overtime_type: str) -> int:
    return {
        REGULAR_OVERTIME: attendance.regular_overtime_minutes,
        NIGHT_DIFFERENTIAL_OVERTIME: attendance.night_differential_overtime_minutes,
        NIGHT_DIFFERENTIAL: attendance.night_differential_minutes,
    }[overtime_type]


def validate_requested_minutes(available_minutes: int, requested_minutes: int) -> None:
    if available_minutes <= 0:
        raise RuleViolationError("There are no calculated minutes available for this overtime type.")
    if requested_minutes > available_minutes:
        raise RuleViolationError(
            f"Requested minutes cannot exceed the calculated {available_minutes} minutes."
        )


def resolve_requested_period(
    attendance: OvertimeAttendance,
    overtime_type: str,
    requested_start_at: Optional[datetime],
    requested_end_at: Optional[datetime],
) -> tuple[datetime, datetime]:
    actual_start = attendance.effective_clock_in
    actual_end = attendance.effective_clock_out
    if actual_start is None or actual_end is None:
        raise RuleViolationError("The attendance record has no valid completed punch interval.")
    if requested_start_at is not None and requested_end_at is not None:
        return requested_start_at, requested_end_at
    if overtime_type == NIGHT_DIFFERENTIAL:
        return actual_start, actual_end
    if attendance.expected_clock_out_at is not None and actual_end > attendance.expected_clock_out_at:
        return attendance.expected_clock_out_at, actual_end
    if attendance.expected_clock_in_at is not None and actual_start < attendance.expected_clock_in_at:
        return actual_start, attendance.expected_clock_in_at
    raise RuleViolationError("No eligible overtime interval is recorded for this attendance.")


def validate_decision(
    application: OvertimeApplication,
    employee_id: UUID,
    actor_employee_id: Optional[UUID],
    decision: str,
    approved_minutes: int,
) -> None:
    if actor_employee_id == employee_id:
        raise PermissionDeniedError("You cannot approve your own overtime application.")
    if decision == "REJECTED" and approved_minutes != 0:
        raise RuleViolationError("Rejected applications must have zero approved minutes.")
    if decision == "APPROVED":
        if approved_minutes <= 0:
            raise RuleViolationError("An approved application must have positive approved minutes.")
        if approved_minutes > application.requested_minutes:
            raise RuleViolationError("Approved minutes cannot exceed the requested minutes.")


def apply_application_totals(
    attendance: OvertimeAttendance,
    applications_newest_first: Iterable[OvertimeApplication],
) -> None:
    """Recomputes the attendance overtime summary from its latest application per type."""
    latest_by_type: dict[str, OvertimeApplication] = {}
    for application in applications_newest_first:
        latest_by_type.setdefault(application.overtime_type, application)

    statuses = []
    for overtime_type, (requested_field, approved_field) in _CATEGORY_FIELDS.items():
        application = latest_by_type.get(overtime_type)
        setattr(attendance, requested_field, application.requested_minutes if application else 0)
        approved_minutes = (
            application.final_payable_minutes or 0
            if application is not None and application.status == "APPROVED"
            else 0
        )
        if approved_field is not None:
            setattr(attendance, approved_field, approved_minutes)
        if application is not None:
            statuses.append(application.status)

    if not statuses:
        attendance.overtime_request_status = None
    elif "PENDING" in statuses:
        attendance.overtime_request_status = "PENDING"
    elif "APPROVED" in statuses:
        attendance.overtime_request_status = "APPROVED"
    else:
        attendance.overtime_request_status = "REJECTED"

    attendance.approved_night_differential_minutes = attendance.night_differential_minutes
    attendance.approved_ot_worked = (
        attendance.approved_regular_overtime_minutes
        + attendance.approved_night_differential_overtime_minutes
    ) / 60
    attendance.approved_night_diff = attendance.night_differential_minutes / 60
