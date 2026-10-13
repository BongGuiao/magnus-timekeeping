from uuid import UUID

from app.attendance.application.punch_ports import DeviceAction
from app.core.generics.uow import GenUnitOfWork
from app.filemaintenance.devices.application.device_proof import (
    consume_device_challenge,
    issue_device_challenge,
)


class DeviceChallengeProofService:
    """Delegates to the device-registration module's challenge and signature verification."""

    def __init__(self, uow: GenUnitOfWork):
        self._uow = uow

    async def issue(self, user_id: UUID, device_uuid: str, action: DeviceAction) -> dict[str, str]:
        return await issue_device_challenge(self._uow, user_id, device_uuid, action)

    async def consume(
        self, user_id: UUID, challenge_id: UUID, action: DeviceAction, signature: str
    ) -> dict[str, str]:
        return await consume_device_challenge(self._uow, user_id, challenge_id, action, signature)
