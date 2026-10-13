from typing import Literal, Protocol
from uuid import UUID

DeviceAction = Literal["CLOCK", "BREAK"]


class DeviceProofService(Protocol):
    async def issue(self, user_id: UUID, device_uuid: str, action: DeviceAction) -> dict[str, str]:
        """Creates a one-time challenge for the user's approved device; raises ValueError if refused."""
        ...

    async def consume(
        self, user_id: UUID, challenge_id: UUID, action: DeviceAction, signature: str
    ) -> dict[str, str]:
        """Verifies a signed challenge and returns the proven device; raises ValueError if refused."""
        ...
