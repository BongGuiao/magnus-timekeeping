from datetime import datetime, timedelta, timezone


MAX_OPEN_ATTENDANCE_AGE = timedelta(hours=22)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def open_shift_expired(clock_in_at: datetime, now: datetime) -> bool:
    return to_utc(now) - to_utc(clock_in_at) >= MAX_OPEN_ATTENDANCE_AGE
