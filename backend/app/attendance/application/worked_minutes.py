from datetime import datetime
from typing import Any


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
