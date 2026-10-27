from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass
class LocationEntity:
    company_id: UUID
    location_code: str
    location_name: str
    location_type: str
    address_line1: str | None = None
    region: str | None = None
    psgc_region_code: str | None = None
    psgc_province_code: str | None = None
    psgc_city_code: str | None = None
    ncr_district: str | None = None
    psgc_barangay_code: str | None = None
    barangay: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    geo_point: str | None = None
    timezone: str = "Asia/Manila"
    status: str = "ACTIVE"
    is_active: bool = True
    created_by: UUID | None = None
    updated_by: UUID | None = None
    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int | None = None
