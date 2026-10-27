from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


NONWORKING_DAY_TYPES = frozenset({"RH", "DBL", "SNW"})


@dataclass(frozen=True)
class ShiftCoverage:
    """A scheduled shift and how much of its required time is still uncovered."""

    work_date: date
    scheduled_start: datetime
    scheduled_end: datetime
    capacity_minutes: int
    worked_start: datetime | None = None
    worked_end: datetime | None = None


def requires_scheduled_work(work_type: str, day_type: str) -> bool:
    return (
        work_type.upper() != "REST"
        and day_type.upper() not in NONWORKING_DAY_TYPES
    )


def scheduled_work_minutes(
    required_minutes: int | None,
    late_minutes: int,
    undertime_minutes: int,
    work_type: str = "REG",
    day_type: str = "REG",
) -> int | None:
    if required_minutes is None:
        return None
    if not requires_scheduled_work(work_type, day_type):
        return 0
    return max(
        0,
        required_minutes - max(late_minutes, 0) - max(undertime_minutes, 0),
    )


def net_worked_minutes(
    clock_in_at: datetime | None,
    clock_out_at: datetime | None,
    punch_metadata: dict[str, Any] | None,
) -> int | None:
    if clock_in_at is None or clock_out_at is None or clock_out_at < clock_in_at:
        return None
    elapsed_minutes = int((clock_out_at - clock_in_at).total_seconds() // 60)
    nonpayable_minutes = (punch_metadata or {}).get("break_calculation", {}).get(
        "net_nonpayable_minutes", 0
    )
    return max(0, elapsed_minutes - nonpayable_minutes)


def shift_coverage(
    *,
    work_date: date,
    expected_clock_in_at: datetime | None,
    expected_clock_out_at: datetime | None,
    required_minutes: int | None,
    credited_work_minutes: int,
    work_type: str = "REG",
    day_type: str = "REG",
    clock_in_at: datetime | None = None,
    clock_out_at: datetime | None = None,
) -> ShiftCoverage | None:
    if (
        expected_clock_in_at is None
        or expected_clock_out_at is None
        or expected_clock_out_at <= expected_clock_in_at
        or not requires_scheduled_work(work_type, day_type)
    ):
        return None
    return ShiftCoverage(
        work_date=work_date,
        scheduled_start=expected_clock_in_at,
        scheduled_end=expected_clock_out_at,
        capacity_minutes=max(0, (required_minutes or 0) - max(credited_work_minutes, 0)),
        worked_start=clock_in_at,
        worked_end=clock_out_at,
    )


def _overlap_seconds(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> float:
    return max(0.0, (min(first_end, second_end) - max(first_start, second_start)).total_seconds())


def allocate_official_business_minutes(
    start_at: datetime,
    end_at: datetime,
    approved_minutes: int,
    shifts: list[ShiftCoverage],
    used_minutes: dict[date, int] | None = None,
) -> dict[date, int]:
    """Credit official business only inside scheduled shifts and outside punched time.

    Credit per shift is capped at the shift's remaining required minutes, so
    worked time plus official business never exceeds the schedule. Pass the same
    ``used_minutes`` mapping across requests to share each shift's capacity.
    """
    used = used_minutes if used_minutes is not None else {}
    remaining = max(approved_minutes, 0)
    allocation: dict[date, int] = {}
    for shift in sorted(shifts, key=lambda item: item.scheduled_start):
        if remaining <= 0:
            break
        window_start = max(start_at, shift.scheduled_start)
        window_end = min(end_at, shift.scheduled_end)
        if window_end <= window_start:
            continue
        seconds = (window_end - window_start).total_seconds()
        if shift.worked_start is not None:
            seconds -= _overlap_seconds(
                window_start,
                window_end,
                shift.worked_start,
                shift.worked_end or shift.scheduled_end,
            )
        capacity = shift.capacity_minutes - used.get(shift.work_date, 0)
        credited = min(int(seconds // 60), capacity, remaining)
        if credited <= 0:
            continue
        allocation[shift.work_date] = allocation.get(shift.work_date, 0) + credited
        used[shift.work_date] = used.get(shift.work_date, 0) + credited
        remaining -= credited
    return allocation
