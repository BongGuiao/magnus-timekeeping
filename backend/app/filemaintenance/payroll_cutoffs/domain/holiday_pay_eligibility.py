"""Regular-holiday pay eligibility (Labor Code Art. 94 and its implementing rules).

An employee who does not work on a regular holiday is paid only if present, or on paid
leave, on the workday immediately preceding the holiday. Rest days and other non-working
days are skipped when locating that workday. Work performed on a skipped day (for example
the first of two successive regular holidays) counts as presence. A company may also
require presence on the workday immediately following the holiday.
"""

from dataclasses import dataclass
from typing import Literal

HolidayPayAttendanceRule = Literal["BEFORE_ONLY", "BEFORE_AND_AFTER"]
HOLIDAY_PAY_ATTENDANCE_RULES: tuple[HolidayPayAttendanceRule, ...] = (
    "BEFORE_ONLY",
    "BEFORE_AND_AFTER",
)
DEFAULT_HOLIDAY_PAY_ATTENDANCE_RULE: HolidayPayAttendanceRule = "BEFORE_ONLY"
HOLIDAY_PAY_LOOKUP_DAYS = 14

DayAttendanceStatus = Literal["PRESENT", "ABSENT", "SKIP", "UNKNOWN"]
WorkdayStatus = Literal["PRESENT", "ABSENT", "UNKNOWN"]


@dataclass(frozen=True)
class DayAttendanceFacts:
    """What is known about one employee on one calendar day next to a holiday."""

    worked: bool
    is_workday: bool
    employed: bool = True
    is_future: bool = False
    paid_leave: bool = False
    official_business: bool = False
    unpaid_leave: bool = False
    schedule_credited: bool = False


def classify_day(facts: DayAttendanceFacts) -> DayAttendanceStatus:
    if facts.worked:
        return "PRESENT"
    if facts.is_future or not facts.employed:
        return "UNKNOWN"
    if not facts.is_workday:
        return "SKIP"
    if facts.paid_leave or facts.official_business:
        return "PRESENT"
    if facts.unpaid_leave:
        return "ABSENT"
    if facts.schedule_credited:
        return "PRESENT"
    return "ABSENT"


def holiday_pay_qualifies(
    rule: HolidayPayAttendanceRule,
    before: WorkdayStatus,
    after: WorkdayStatus,
) -> bool:
    """UNKNOWN never disqualifies: no workday found, not yet employed, or not yet occurred."""
    if before == "ABSENT":
        return False
    if rule == "BEFORE_AND_AFTER" and after == "ABSENT":
        return False
    return True
