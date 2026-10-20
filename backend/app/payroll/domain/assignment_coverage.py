from datetime import date, timedelta
from typing import Iterable


def require_exact_assignment_coverage(
    effective_from: date,
    effective_to: date | None,
    assignment_periods: Iterable[tuple[date, date | None, date | None]],
) -> None:
    intervals = []
    for assignment_from, assignment_to, separation_date in assignment_periods:
        end_dates = [end for end in (assignment_to, separation_date) if end is not None]
        assignment_end = min(end_dates) if end_dates else None
        if assignment_end is not None and assignment_end < effective_from:
            continue
        if effective_to is not None and assignment_from > effective_to:
            continue
        start = max(assignment_from, effective_from)
        end = min(assignment_end, effective_to) if assignment_end is not None and effective_to is not None else (
            assignment_end if effective_to is None else effective_to
        )
        intervals.append((start, end))

    intervals.sort(key=lambda interval: interval[0])
    expected_start = effective_from
    covered_open_ended = False
    for start, end in intervals:
        if covered_open_ended or start < expected_start:
            raise ValueError(
                "Compensation dates must be covered by exactly one active employment "
                "assignment to the selected payroll group."
            )
        if start > expected_start:
            raise ValueError(
                "Compensation dates must be covered by exactly one active employment "
                "assignment to the selected payroll group."
            )
        if end is None:
            covered_open_ended = True
        else:
            expected_start = end + timedelta(days=1)

    covered_to_end = covered_open_ended or (
        effective_to is not None and expected_start > effective_to
    )
    if not covered_to_end:
        raise ValueError(
            "Compensation dates must be covered by exactly one active employment "
            "assignment to the selected payroll group."
        )
