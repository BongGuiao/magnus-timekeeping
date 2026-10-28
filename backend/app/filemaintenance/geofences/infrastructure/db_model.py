from sqlalchemy import Column, String, Numeric, Integer, DateTime, Boolean, CheckConstraint, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography
from sqlalchemy.orm import declarative_base
from app.core.database import Base

class Geofence(Base):
    __tablename__ = 'geofences'
    __table_args__ = (
        UniqueConstraint('company_id', 'geofence_code', name='uq_company_geofence_code'),
        UniqueConstraint('company_id', 'id', name='uq_geofences_company_id_id'),
        CheckConstraint('radius_meters IS NULL OR radius_meters > 0', name='chk_radius_meters'),
        CheckConstraint('center_point IS NOT NULL OR boundary_polygon IS NOT NULL', name='chk_geometry_present'),
        CheckConstraint('effective_to IS NULL OR effective_to > effective_from', name='chk_effective_dates'),
        CheckConstraint('maximum_gps_accuracy_meters > 0', name='chk_gps_accuracy'),
        {'schema': 'location'}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    company_id = Column(UUID(as_uuid=True), nullable=False)
    location_id = Column(UUID(as_uuid=True), nullable=True)
    geofence_code = Column(String(50), nullable=False)
    geofence_name = Column(String(150), nullable=False)
    geofence_type = Column(String(30), nullable=False)
    
    # PostGIS Spatial Fields (SRID 4326)
    center_point = Column(Geography(geometry_type='POINT', srid=4326), nullable=True)
    radius_meters = Column(Numeric(8, 2), nullable=True)
    boundary_polygon = Column(Geography(geometry_type='POLYGON', srid=4326), nullable=True)
    
    maximum_gps_accuracy_meters = Column(Integer, nullable=False, server_default='100')
    effective_from = Column(DateTime(timezone=True), nullable=False)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    source_type = Column(String(30), nullable=False)
    source_reference_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, server_default='ACTIVE')
    
    # Audit & Versioning Fields
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    row_version = Column(Integer, nullable=False, server_default='1')
    is_active = Column(Boolean, nullable=False, server_default='true')
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(UUID(as_uuid=True), nullable=True)