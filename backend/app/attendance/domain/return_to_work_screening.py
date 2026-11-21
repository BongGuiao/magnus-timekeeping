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
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ReviewDay:
    work_date: date
    status: ReviewDayStatus


def current_absence_evidence(days: Iterable[ReviewDay]) -> tuple[date, ...]:
    """Return the three most recent marked absences if a current streak is established.

    Days must be complete and ordered from newest to oldest. Unknown evidence
    stops screening rather than treating missing records as an absence.
    """
    absent: list[date] = []
    previous_date: date | None = None
    for day in days:
        if previous_date is not None and day.work_date != previous_date - timedelta(days=1):
            raise ValueError("Review days must be consecutive and ordered newest first.")
        previous_date = day.work_date
        if day.status == ReviewDayStatus.ABSENT:
            absent.append(day.work_date)
            if len(absent) == 3:
                return tuple(reversed(absent))
        elif day.status not in (ReviewDayStatus.REST_DAY, ReviewDayStatus.HOLIDAY):
            return ()
    return ()
