from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID


@dataclass
class AssignedLocation:
    id: UUID
    company_id: UUID
    location_code: str
    location_name: str
    authorized_geofence_ids: list[UUID] = field(default_factory=list)


@dataclass
class SiteGeofence:
    id: UUID
    company_id: UUID
    location_id: UUID
    geofence_name: str
    shape: str
    latitude: Optional[float]
    longitude: Optional[float]
    radius_meters: Optional[float]
    maximum_gps_accuracy_meters: int


@dataclass
class WfhRegistration:
    geofence_id: UUID
    latitude: float
    longitude: float
    is_active: bool


@dataclass
class AuthorizedGeofence:
    geofence_id: UUID
    geofence_name: str
    shape: str
    latitude: Optional[float]
    longitude: Optional[float]
    radius_meters: Optional[float]
    maximum_gps_accuracy_meters: int


@dataclass
class AuthorizedLocation:
    company_id: UUID
    location_id: UUID
    location_code: str
    location_name: str
    geofences: list[AuthorizedGeofence] = field(default_factory=list)
    location_type: str = "OFFICE"
