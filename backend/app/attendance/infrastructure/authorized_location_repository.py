from datetime import date, datetime
from typing import Optional, Sequence
from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.domain.entities.authorized_location import (
    AssignedLocation,
    SiteGeofence,
    WfhRegistration,
)
from app.filemaintenance.employees.infrastructure.db_model import (
    EmploymentAssignmentModel,
    EmployeeWfhLocationModel,
)
from app.filemaintenance.geofences.infrastructure.db_model import Geofence
from app.filemaintenance.location.infrastructure.db_model import Location as LocationModel


def _float_or_none(value) -> Optional[float]:
    return float(value) if value is not None else None


class SqlAlchemyAuthorizedLocationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_assigned_locations(self, employee_id: UUID, today: date) -> list[AssignedLocation]:
        rows = (
            await self._session.execute(
                select(LocationModel)
                .join(
                    EmploymentAssignmentModel,
                    and_(
                        EmploymentAssignmentModel.primary_location_id == LocationModel.id,
                        EmploymentAssignmentModel.company_id == LocationModel.company_id,
                    ),
                )
                .where(
                    EmploymentAssignmentModel.employee_id == employee_id,
                    EmploymentAssignmentModel.is_active.is_(True),
                    EmploymentAssignmentModel.status == "ACTIVE",
                    EmploymentAssignmentModel.effective_from <= today,
                    or_(
                        EmploymentAssignmentModel.effective_to.is_(None),
                        EmploymentAssignmentModel.effective_to >= today,
                    ),
                    or_(
                        EmploymentAssignmentModel.separation_date.is_(None),
                        EmploymentAssignmentModel.separation_date >= today,
                    ),
                    LocationModel.is_active.is_(True),
                    LocationModel.status == "ACTIVE",
                )
                .distinct()
                .order_by(LocationModel.location_name)
            )
        ).scalars().all()
        return [
            AssignedLocation(
                id=row.id,
                company_id=row.company_id,
                location_code=row.location_code,
                location_name=row.location_name,
            )
            for row in rows
        ]

    async def list_active_geofences(
        self, locations: Sequence[AssignedLocation], now: datetime
    ) -> list[SiteGeofence]:
        center = func.coalesce(
            cast(Geofence.center_point, Geometry(srid=4326)),
            func.ST_Centroid(cast(Geofence.boundary_polygon, Geometry(srid=4326))),
        )
        rows = (
            await self._session.execute(
                select(
                    Geofence,
                    func.ST_Y(center).label("latitude"),
                    func.ST_X(center).label("longitude"),
                ).where(
                    or_(
                        *(
                            and_(
                                Geofence.company_id == location.company_id,
                                Geofence.location_id == location.id,
                            )
                            for location in locations
                        )
                    ),
                    Geofence.is_active.is_(True),
                    Geofence.status == "ACTIVE",
                    Geofence.effective_from <= now,
                    or_(Geofence.effective_to.is_(None), Geofence.effective_to >= now),
                )
            )
        ).all()
        return [
            SiteGeofence(
                id=geofence.id,
                company_id=geofence.company_id,
                location_id=geofence.location_id,
                geofence_name=geofence.geofence_name,
                shape="POLYGON" if geofence.boundary_polygon is not None else "CIRCLE",
                latitude=_float_or_none(latitude),
                longitude=_float_or_none(longitude),
                radius_meters=_float_or_none(geofence.radius_meters),
                maximum_gps_accuracy_meters=geofence.maximum_gps_accuracy_meters,
            )
            for geofence, latitude, longitude in rows
        ]

    async def get_wfh_registration(self, employee_id: UUID) -> Optional[WfhRegistration]:
        row = await self._session.get(EmployeeWfhLocationModel, employee_id)
        if row is None:
            return None
        return WfhRegistration(
            geofence_id=row.geofence_id,
            latitude=row.latitude,
            longitude=row.longitude,
            is_active=row.is_active,
        )
