import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from uuid import UUID

from pydantic import ValidationError

from app.attendance.application.clock import utc_now
from app.attendance.application.recent_attendance_ports import (
    RecentAttendanceSnapshotCache,
    RecentAttendanceSnapshotLoader,
    SnapshotStoreError,
)
from app.attendance.application.recent_attendance_snapshot import RecentAttendanceSnapshot
from app.attendance.domain.exceptions import SnapshotUnavailableError
from app.core.generics.uc_base import BaseUseCase

logger = logging.getLogger(__name__)


@dataclass
class GetRecentAttendanceSnapshotInput:
    user_id: UUID
    force_refresh: bool = False


class GetRecentAttendanceSnapshotUseCase(BaseUseCase[RecentAttendanceSnapshot]):
    """Serves the cached dashboard snapshot, or recomputes and re-caches it on demand."""

    def __init__(
        self,
        loader: RecentAttendanceSnapshotLoader,
        cache: RecentAttendanceSnapshotCache,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._loader = loader
        self._cache = cache
        self._clock = clock

    async def _execute(self, data: GetRecentAttendanceSnapshotInput) -> RecentAttendanceSnapshot:
        if data.force_refresh:
            return await self._refresh(data.user_id)
        return await self._read_cached(data.user_id)

    async def _refresh(self, user_id: UUID) -> RecentAttendanceSnapshot:
        live = await self._loader.load(user_id) or {
            "records": [],
            "weekly_hours_worked": 0,
            "weekly_minutes_worked": 0,
            "missed_clock_ins_this_month": 0,
            "refreshed_at": self._clock().isoformat(),
        }
        snapshot = RecentAttendanceSnapshot.model_validate(live)
        try:
            await self._cache.write(user_id, snapshot)
        except SnapshotStoreError:
            logger.exception(
                "Fresh attendance snapshot was loaded, but its cache could not be updated.",
                extra={"user_id": str(user_id)},
            )
        return snapshot

    async def _read_cached(self, user_id: UUID) -> RecentAttendanceSnapshot:
        try:
            serialized, refreshed_at = await self._cache.read(user_id)
        except SnapshotStoreError as error:
            raise SnapshotUnavailableError(
                "The recent attendance dashboard snapshot is temporarily unavailable."
            ) from error
        if serialized is None and refreshed_at is not None:
            return RecentAttendanceSnapshot(records=[], refreshed_at=refreshed_at)
        if serialized is None:
            raise SnapshotUnavailableError(
                "The recent attendance dashboard snapshot has not been generated yet. Please try again shortly."
            )
        try:
            return RecentAttendanceSnapshot.model_validate_json(serialized)
        except ValidationError as error:
            raise SnapshotUnavailableError(
                "The recent attendance dashboard snapshot is invalid. Please try again after the next refresh."
            ) from error
