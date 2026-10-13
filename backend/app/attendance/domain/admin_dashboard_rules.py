from datetime import datetime, timedelta
from typing import Iterable

from app.attendance.domain.entities.admin_dashboard import AttendanceException, TeamAttendanceDay

NO_LOGOUT_GRACE = timedelta(hours=6)


def classify_attendance_exceptions(
    days: Iterable[TeamAttendanceDay], now: datetime
) -> tuple[list[AttendanceException], list[AttendanceException]]:
    """Splits team attendance into (no login, no logout); days on leave are never exceptions."""
    no_login: list[AttendanceException] = []
    no_logout: list[AttendanceException] = []
    for day in days:
        if day.leave_type:
            continue
        exception = AttendanceException(
            employee=day.employee,
            supervisor=day.supervisor,
            work_date=day.work_date,
            time_in=day.clock_in_at,
            time_out=day.clock_out_at,
        )
        if day.is_absent:
            no_login.append(exception)
        elif (
            day.clock_in_at is not None
            and day.clock_out_at is None
            and day.expected_clock_out_at is not None
            and now >= day.expected_clock_out_at + NO_LOGOUT_GRACE
        ):
            no_logout.append(exception)
    return no_login, no_logout
