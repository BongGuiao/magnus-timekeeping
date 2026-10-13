from typing import Any, Protocol
from uuid import UUID


class RecentAttendanceRefresher(Protocol):
    def request_refresh(self, user_id: UUID) -> None: ...


class AuditTrail(Protocol):
    async def record(
        self,
        *,
        user_id: UUID | str,
        action: str,
        resource: str,
        resource_id: str,
        after: Any,
    ) -> None: ...
