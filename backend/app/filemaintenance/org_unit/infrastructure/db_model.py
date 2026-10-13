import uuid
from datetime import date, datetime
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

class OrgUnit(Base):
    __tablename__ = "org_units"
    __table_args__ = (
        UniqueConstraint("company_id", "org_unit_code", name="uq_company_org_unit_code"),
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'INACTIVE')", 
            name="ck_org_units_status"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", 
            name="ck_org_units_effective_dates"
        ),
        {"schema": "core"}
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        primary_key=True, 
        server_default=func.gen_random_uuid()
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        ForeignKey("core.companies.id"), 
        nullable=False
    )
    parent_org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), 
        ForeignKey("core.org_units.id"), 
        nullable=True
    )
    
    org_unit_code: Mapped[str] = mapped_column(String(30), nullable=False)
    org_unit_name: Mapped[str] = mapped_column(String(150), nullable=False)
    org_unit_type: Mapped[str] = mapped_column(String(30), nullable=False)
    
    manager_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cost_center_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ACTIVE")
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        server_default=func.now(), 
        onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # Optional: Self-referential relationship for parent/child hierarchy navigation
    parent: Mapped["OrgUnit | None"] = relationship(
        "OrgUnit", 
        remote_side=[id], 
        back_populates="children"
    )
    children: Mapped[list["OrgUnit"]] = relationship(
        "OrgUnit", 
        back_populates="parent"
    )