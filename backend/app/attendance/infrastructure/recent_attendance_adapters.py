from typing import Optional
from uuid import UUID

from fastapi.concurrency import run_in_threadpool
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.attendance.application.recent_attendance_ports import SnapshotStoreError
from app.attendance.application.recent_attendance_snapshot import RecentAttendanceSnapshot
from app.core.config import settings
from app.tasks.dashboard_tasks import (
    RECENT_ATTENDANCE_SNAPSHOT_PREFIX,
    RECENT_ATTENDANCE_SNAPSHOT_REFRESHED_AT_KEY,
    load_recent_attendance_snapshots,
)


class TaskRecentAttendanceSnapshotLoader:
    """Computes snapshots with the same synchronous routine the Celery refresh task uses."""

    async def load(self, user_id: UUID) -> Optional[dict]:
        snapshots = await run_in_threadpool(load_recent_attendance_snapshots, str(user_id))
        return snapshots.get(str(user_id))


class RedisRecentAttendanceSnapshotCache:
    @staticmethod
    def _connect() -> Redis:
        url = settings.DASHBOARD_CACHE_REDIS_URL or f"redis://{settings.REDIS_HOST}:6379/1"
        return Redis.from_url(url, decode_responses=True)

    async def read(self, user_id: UUID) -> tuple[Optional[str], Optional[str]]:
        cache = self._connect()
        try:
            serialized, refreshed_at = await cache.mget(
                f"{RECENT_ATTENDANCE_SNAPSHOT_PREFIX}:{user_id}",
                RECENT_ATTENDANCE_SNAPSHOT_REFRESHED_AT_KEY,
            )
            return serialized, refreshed_at
        except RedisError as error:
            raise SnapshotStoreError(str(error)) from error
        finally:
            await cache.aclose()

    async def write(self, user_id: UUID, snapshot: RecentAttendanceSnapshot) -> None:
        cache = self._connect()
        try:
            await cache.set(
                f"{RECENT_ATTENDANCE_SNAPSHOT_PREFIX}:{user_id}",
                snapshot.model_dump_json(),
                ex=settings.DASHBOARD_CACHE_TTL,
            )
            await cache.set(
                RECENT_ATTENDANCE_SNAPSHOT_REFRESHED_AT_KEY,
                snapshot.refreshed_at,
                ex=settings.DASHBOARD_CACHE_TTL,
            )
        except RedisError as error:
            raise SnapshotStoreError(str(error)) from error
        finally:
            await cache.aclose()
