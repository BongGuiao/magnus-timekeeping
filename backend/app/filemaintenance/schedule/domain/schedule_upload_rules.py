"""Pure business rules for supervisor schedule CSV uploads."""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from app.filemaintenance.schedule.domain.entities.schedule_upload import (
    RawScheduleUploadRow,
    RestDayPatternRef,
    ScheduleTemplateRef,
    ScheduleUploadRow,
)

CSV_COLUMNS: tuple[str, ...] = (
    "employee_code",
    "schedule_code",
    "assignment_type",
    "effective_from",
    "effective_to",
    "rest_day_pattern_code",
    "reason",
)
REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {"employee_code", "schedule_code", "assignment_type", "effective_from"}
)
MAX_ROWS_PER_UPLOAD = 1000
# Schedules may only start after today so attendance already computed is never rewritten.
MIN_LEAD_DAYS = 1
MAX_CODE_LENGTH = 30
MAX_REASON_LENGTH = 500
ACTIVE_TEMPLATE_STATUS = "ACTIVE"

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ASSIGNMENT_TYPE = re.compile(r"^[A-Z0-9_]+$")


@dataclass(frozen=True)
class ParsedRow:
    row: ScheduleUploadRow | None
    errors: tuple[str, ...]


def _parse_date(value: str, column: str, errors: list[str]) -> date | None:
    if not _ISO_DATE.match(value):
        errors.append(f"{column} must be a date in YYYY-MM-DD format.")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{column} '{value}' is not a valid calendar date.")
        return None


def _required(value: str, column: str, errors: list[str]) -> str:
    cleaned = value.strip()
    if not cleaned:
        errors.append(f"{column} is required.")
    return cleaned


def _code(value: str, column: str, errors: list[str]) -> str:
    if len(value) > MAX_CODE_LENGTH:
        errors.append(f"{column} must be at most {MAX_CODE_LENGTH} characters.")
    return value


def earliest_allowed_start(today: date) -> date:
    return today + timedelta(days=MIN_LEAD_DAYS)


def parse_row(raw: RawScheduleUploadRow, today: date) -> ParsedRow:
    errors: list[str] = []
    employee_code = _code(_required(raw.employee_code, "employee_code", errors), "employee_code", errors)
    schedule_code = _code(_required(raw.schedule_code, "schedule_code", errors), "schedule_code", errors)

    assignment_type = _required(raw.assignment_type, "assignment_type", errors).upper()
    if assignment_type and not _ASSIGNMENT_TYPE.match(assignment_type):
        errors.append("assignment_type may only contain letters, digits, and underscores.")
    _code(assignment_type, "assignment_type", errors)

    effective_from_text = _required(raw.effective_from, "effective_from", errors)
    effective_from = (
        _parse_date(effective_from_text, "effective_from", errors) if effective_from_text else None
    )
    effective_to_text = raw.effective_to.strip()
    effective_to = _parse_date(effective_to_text, "effective_to", errors) if effective_to_text else None

    if effective_from and effective_from < earliest_allowed_start(today):
        errors.append(
            f"effective_from must be on or after {earliest_allowed_start(today).isoformat()}; "
            "past and same-day schedule changes must be handled by HR."
        )
    if effective_from and effective_to and effective_to < effective_from:
        errors.append("effective_to must be on or after effective_from.")

    rest_day_pattern_code = _code(raw.rest_day_pattern_code.strip(), "rest_day_pattern_code", errors)
    reason = raw.reason.strip()
    if len(reason) > MAX_REASON_LENGTH:
        errors.append(f"reason must be at most {MAX_REASON_LENGTH} characters.")

    if errors or effective_from is None:
        return ParsedRow(row=None, errors=tuple(errors))
    return ParsedRow(
        row=ScheduleUploadRow(
            row_no=raw.row_no,
            employee_code=employee_code,
            schedule_code=schedule_code,
            assignment_type=assignment_type,
            effective_from=effective_from,
            effective_to=effective_to,
            rest_day_pattern_code=rest_day_pattern_code or None,
            reason=reason or None,
        ),
        errors=(),
    )


def periods_overlap(
    first_from: date, first_to: date | None, second_from: date, second_to: date | None
) -> bool:
    return first_from <= (second_to or date.max) and second_from <= (first_to or date.max)


def find_overlapping_rows(rows: Iterable[ScheduleUploadRow]) -> dict[int, list[str]]:
    """Flags rows in the same file that give one employee overlapping schedules."""
    by_employee: dict[str, list[ScheduleUploadRow]] = defaultdict(list)
    for row in rows:
        by_employee[row.employee_code].append(row)

    errors: dict[int, list[str]] = defaultdict(list)
    for employee_rows in by_employee.values():
        for index, row in enumerate(employee_rows):
            for other in employee_rows[index + 1:]:
                if periods_overlap(row.effective_from, row.effective_to, other.effective_from, other.effective_to):
                    errors[row.row_no].append(
                        f"Overlaps row {other.row_no} for the same employee."
                    )
                    errors[other.row_no].append(
                        f"Overlaps row {row.row_no} for the same employee."
                    )
    return dict(errors)


def template_errors(template: ScheduleTemplateRef, row: ScheduleUploadRow) -> list[str]:
    if not template.is_active or template.status != ACTIVE_TEMPLATE_STATUS:
        return [f"Schedule {template.schedule_code} is not active."]
    starts_in_time = template.effective_from <= row.effective_from
    ends_in_time = template.effective_to is None or (
        row.effective_to is not None and row.effective_to <= template.effective_to
    )
    if starts_in_time and ends_in_time:
        return []
    until = template.effective_to.isoformat() if template.effective_to else "open-ended"
    return [
        f"Schedule {template.schedule_code} is only effective from "
        f"{template.effective_from.isoformat()} to {until}."
    ]


def rest_day_pattern_errors(pattern: RestDayPatternRef) -> list[str]:
    if not pattern.is_active:
        return [f"Rest day pattern {pattern.pattern_code} is not active."]
    return []


def format_batch_no(year: int, sequence: int) -> str:
    return f"SCH-{year}-{sequence:06d}"
