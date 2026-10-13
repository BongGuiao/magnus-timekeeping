from typing import Optional, Protocol
from uuid import UUID

from app.attendance.application.recent_attendance_snapshot import RecentAttendanceSnapshot


class SnapshotStoreError(Exception):
    """The snapshot cache could not be read or written."""


class RecentAttendanceSnapshotLoader(Protocol):
    async def load(self, user_id: UUID) -> Optional[dict]:
        """Computes the employee's snapshot from live attendance; None when there is none."""
        ...


class RecentAttendanceSnapshotCache(Protocol):
    async def read(self, user_id: UUID) -> tuple[Optional[str], Optional[str]]:
        """Returns (serialized snapshot, global refreshed-at marker); raises SnapshotStoreError."""
        ...

    async def write(self, user_id: UUID, snapshot: RecentAttendanceSnapshot) -> None:
        """Raises SnapshotStoreError."""
        ...
