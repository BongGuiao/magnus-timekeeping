import logging
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from kombu.exceptions import OperationalError

from app.audit.service import log_entity_action
from app.tasks.dashboard_tasks import refresh_recent_attendance_snapshot

logger = logging.getLogger(__name__)


def queue_recent_attendance_refresh(user_id: UUID) -> None:
    try:
        refresh_recent_attendance_snapshot.delay(str(user_id))
    except OperationalError:
        logger.exception(
            "Attendance was saved, but its dashboard snapshot refresh could not be queued.",
            extra={"user_id": str(user_id)},
        )


class CeleryRecentAttendanceRefresher:
    def request_refresh(self, user_id: UUID) -> None:
        queue_recent_attendance_refresh(user_id)


class ElasticsearchAuditTrail:
    def __init__(self, es_client: AsyncElasticsearch | None):
        self._es_client = es_client

    async def record(
        self,
        *,
        user_id: UUID | str,
        action: str,
        resource: str,
        resource_id: str,
        after: Any,
    ) -> None:
        await log_entity_action(
            self._es_client,
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            after=after,
        )
