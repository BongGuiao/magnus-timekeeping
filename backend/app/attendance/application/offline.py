from typing import Protocol
from uuid import UUID

from anyio import to_thread
from app.attendance.application.ports import AuditTrail, RecentAttendanceRefresher
from app.core.generics.uc_base import BaseUseCase


class OfflineAttendanceGateway(Protocol):
    async def prepare(self, user_id: UUID, device_uuid: str) -> dict: ...
    async def ingest(self, user_id: UUID, payload_json: str, signature: str, image: bytes) -> dict: ...


class PrepareOfflineAttendanceUseCase(BaseUseCase[dict]):
    def __init__(self, gateway: OfflineAttendanceGateway):
        self._gateway = gateway

    async def _execute(self, user_id: UUID, device_uuid: str) -> dict:
        return await self._gateway.prepare(user_id, device_uuid)


class SyncOfflineAttendanceUseCase(BaseUseCase[dict]):
    def __init__(self, gateway: OfflineAttendanceGateway, refresher: RecentAttendanceRefresher, audit: AuditTrail):
        self._gateway = gateway
        self._refresher = refresher
        self._audit = audit

    async def _execute(self, user_id: UUID, payload_json: str, signature: str, image: bytes) -> dict:
        result = await self._gateway.ingest(user_id, payload_json, signature, image)
        if result["status"] == "ACCEPTED":
            await to_thread.run_sync(self._refresher.request_refresh, user_id)
        await self._audit.record(user_id=user_id, action="CREATE", resource="offline_attendance",
                                 resource_id=result["event_id"], after=result)
        return result
