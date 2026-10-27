import uuid
from datetime import datetime
from typing import Optional
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime, Integer, Boolean
from geoalchemy2 import Geography
from app.core.database import Base
# Registers the "CompanyModel" relationship target when this model is imported on its own.
from app.filemaintenance.companies.infrastructure.db_model import CompanyModel  # noqa: F401

class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        # Multi-tenancy unique constraint
        UniqueConstraint("company_id", "location_code", name="uq_locations_company_code"),
        UniqueConstraint("company_id", "id", name="uq_locations_company_id_id"),
        # Latitude validation: -90 to 90
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="chk_locations_latitude_range",
        ),
        # Longitude validation: -180 to 180
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="chk_locations_longitude_range",
        ),
        # Location type enum check constraint
        CheckConstraint(
            "location_type IN ('OFFICE', 'WAREHOUSE', 'DISPATCH', 'CUSTOMER', 'FIELD', 'FLEET_YARD', 'OTHER')",
            name="chk_locations_type_valid",
        ),
        CheckConstraint(
            "(psgc_region_code IS NULL OR psgc_region_code ~ '^[0-9]{9}$') "
            "AND (psgc_province_code IS NULL OR psgc_province_code ~ '^[0-9]{9}$') "
            "AND (psgc_city_code IS NULL OR psgc_city_code ~ '^[0-9]{9}$') "
            "AND (psgc_barangay_code IS NULL OR psgc_barangay_code ~ '^[0-9]{9}$')",
            name="chk_locations_psgc_codes",
        ),
        CheckConstraint(
            "ncr_district IS NULL OR ncr_district IN "
            "('NCR_1ST_DISTRICT', 'NCR_2ND_DISTRICT', 'NCR_3RD_DISTRICT', 'NCR_4TH_DISTRICT')",
            name="chk_locations_ncr_district",
        ),
        {"schema": "core"},
    )

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # Foreign Keys & References
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core.companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Business Codes & Core Attributes
    location_code: Mapped[str] = mapped_column(String(30), nullable=False)
    location_name: Mapped[str] = mapped_column(String(150), nullable=False)
    location_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Address / Regional Details
    address_line1: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    psgc_region_code: Mapped[Optional[str]] = mapped_column(String(9), nullable=True)
    psgc_province_code: Mapped[Optional[str]] = mapped_column(String(9), nullable=True)
    psgc_city_code: Mapped[Optional[str]] = mapped_column(String(9), nullable=True)
    ncr_district: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    psgc_barangay_code: Mapped[Optional[str]] = mapped_column(String(9), nullable=True)
    barangay: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    province: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Coordinates & Spatial Data
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    
    # PostGIS geography point in WGS84 / SRID 4326
    geo_point: Mapped[Optional[str]] = mapped_column(
        Geography(
            geometry_type="POINT",
            srid=4326,
            spatial_index=True,
            use_typmod=True,
        ),
        nullable=True,
    )

    # Settings & Status
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'Asia/Manila'")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'ACTIVE'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    # Concurrency Control
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )

    # Audit Trail
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    company = relationship("CompanyModel", back_populates="locations")