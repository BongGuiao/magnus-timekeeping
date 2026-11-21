from dataclasses import dataclass
from datetime import date
from uuid import UUID


@dataclass(frozen=True)
class AttendanceDayFact:
    employee_id: UUID
    work_date: date
    record_id: UUID
    late_minutes: int


@dataclass(frozen=True)
class TardinessCandidate:
    employee_id: UUID
    late_dates: tuple[date, ...]
    duplicate_dates: tuple[date, ...]
    pending_correction_dates: tuple[date, ...]


def previous_calendar_month(today: date) -> tuple[date, date]:
    end = today.replace(day=1).toordinal() - 1
    last_day = date.fromordinal(end)
    return last_day.replace(day=1), last_day


def screen_tardiness(
    attendance: list[AttendanceDayFact],
    pending_corrections: list[tuple[UUID, date]],
    period_start: date,
    period_end: date,
) -> list[TardinessCandidate]:
    if period_end < period_start:
        raise ValueError("The screening period end must not precede its start.")
    records_by_day: dict[tuple[UUID, date], list[AttendanceDayFact]] = {}
    for record in attendance:
        if period_start <= record.work_date <= period_end:
            records_by_day.setdefault((record.employee_id, record.work_date), []).append(record)

    late_by_employee: dict[UUID, list[date]] = {}
    duplicates_by_employee: dict[UUID, list[date]] = {}
    for (employee_id, work_date), records in records_by_day.items():
        if any(record.late_minutes > 0 for record in records):
            late_by_employee.setdefault(employee_id, []).append(work_date)
        if len({record.record_id for record in records}) > 1:
            duplicates_by_employee.setdefault(employee_id, []).append(work_date)

    pending_by_employee: dict[UUID, set[date]] = {}
    for employee_id, work_date in pending_corrections:
        if period_start <= work_date <= period_end:
            pending_by_employee.setdefault(employee_id, set()).add(work_date)

    return [
        TardinessCandidate(
            employee_id=employee_id,
            late_dates=tuple(sorted(late_dates)),
            duplicate_dates=tuple(sorted(duplicates_by_employee.get(employee_id, []))),
            pending_correction_dates=tuple(sorted(pending_by_employee.get(employee_id, set()))),
        )
        for employee_id, late_dates in sorted(late_by_employee.items(), key=lambda item: str(item[0]))
        if len(late_dates) >= 4
    ]
