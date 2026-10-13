from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

PH_TIMEZONE = ZoneInfo("Asia/Manila")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ph_today(now: datetime) -> date:
    return now.astimezone(PH_TIMEZONE).date()
