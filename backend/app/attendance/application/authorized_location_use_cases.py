from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from uuid import UUID

from app.attendance.application.authorized_location_ports import AuthorizedLocationUnitOfWork
from app.attendance.application.clock import ph_today, utc_now
from app.attendance.domain.authorized_sites import build_authorized_sites
from app.attendance.domain.entities.authorized_location import AuthorizedLocation
from app.core.generics.uc_base import BaseUseCase


@dataclass
class ListMyAttendanceLocationsInput:
    employee_id: UUID
    include_wfh: bool


class ListMyAttendanceLocationsUseCase(BaseUseCase[list[AuthorizedLocation]]):
    """Sites where an employee may punch. Informational; the clock use case re-validates GPS."""

    def __init__(self, uow: AuthorizedLocationUnitOfWork, clock: Callable[[], datetime] = utc_now):
        self._uow = uow
        self._clock = clock

    async def _execute(self, data: ListMyAttendanceLocationsInput) -> list[AuthorizedLocation]:
        now = self._clock()
        async with self._uow as uow:
            locations = await uow.locations.list_assigned_locations(data.employee_id, ph_today(now))
            if not locations:
                return []
            geofences = await uow.locations.list_active_geofences(locations, now)
            wfh = await uow.locations.get_wfh_registration(data.employee_id) if data.include_wfh else None
        return build_authorized_sites(data.employee_id, locations, geofences, wfh)
