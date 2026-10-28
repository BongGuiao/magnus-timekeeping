from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass
class GeofenceEntity:
    company_id: UUID
    geofence_code: str
    geofence_name: str
    geofence_type: str
    effective_from: datetime
    source_type: str
    location_id: UUID | None = None
    center_point: str | None = None
    radius_meters: Decimal | None = None
    boundary_polygon: str | None = None
    maximum_gps_accuracy_meters: int = 100
    effective_to: datetime | None = None
    source_reference_id: str | None = None
    status: str = "ACTIVE"
    created_at: datetime | None = None
    created_by: UUID | None = None
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    row_version: int = 1
    is_active: bool = True
    id: UUID | None = None
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None
