from datetime import date, datetime
from typing import Optional, Protocol, Sequence
from uuid import UUID

from app.attendance.domain.entities.authorized_location import (
    AssignedLocation,
    SiteGeofence,
    WfhRegistration,
)


class AuthorizedLocationRepository(Protocol):
    async def list_assigned_locations(self, employee_id: UUID, today: date) -> list[AssignedLocation]: ...

    async def list_active_geofences(
        self, locations: Sequence[AssignedLocation], now: datetime
    ) -> list[SiteGeofence]: ...

    async def get_wfh_registration(self, employee_id: UUID) -> Optional[WfhRegistration]: ...


class AuthorizedLocationUnitOfWork(Protocol):
    locations: AuthorizedLocationRepository

    async def __aenter__(self) -> "AuthorizedLocationUnitOfWork": ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...
