from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from collections.abc import Iterable


class ReviewDayStatus(str, Enum):
    ABSENT = "ABSENT"
    REST_DAY = "REST_DAY"
    HOLIDAY = "HOLIDAY"
    APPROVED_LEAVE = "APPROVED_LEAVE"
    APPROVED_BUSINESS = "APPROVED_BUSINESS"
    PRESENT = "PRESENT"
    NOT_ABSENT = "NOT_ABSENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ReviewDay:
    work_date: date
    status: ReviewDayStatus


def _absence_dates(days: Iterable[ReviewDay]) -> Iterable[date]:
    previous_date: date | None = None
    for day in days:
        if previous_date is not None and day.work_date != previous_date - timedelta(days=1):
            raise ValueError("Review days must be consecutive and ordered newest first.")
        previous_date = day.work_date
        if day.status == ReviewDayStatus.ABSENT:
            yield day.work_date
        elif day.status not in (ReviewDayStatus.REST_DAY, ReviewDayStatus.HOLIDAY):
            break


def current_absence_streak(days: Iterable[ReviewDay]) -> tuple[date, ...]:
    """Return all marked absences in the current, fully evidenced streak."""
    return tuple(reversed(list(_absence_dates(days))))


def current_absence_evidence(days: Iterable[ReviewDay]) -> tuple[date, ...]:
    """Return the three most recent marked absences if a current streak is established.

    Days must be complete and ordered from newest to oldest. Unknown evidence
    stops screening rather than treating missing records as an absence.
    """
    absent: list[date] = []
    for work_date in _absence_dates(days):
        absent.append(work_date)
        if len(absent) == 3:
            return tuple(reversed(absent))
    return ()
