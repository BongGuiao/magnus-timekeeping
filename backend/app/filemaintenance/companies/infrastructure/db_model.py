from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, CHAR, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.filemaintenance.location.infrastructure.db_model import Location


class CompanyModel(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'INACTIVE')"),
        CheckConstraint(
            "(psgc_region_code IS NULL OR psgc_region_code ~ '^[0-9]{9}$') "
            "AND (psgc_province_code IS NULL OR psgc_province_code ~ '^[0-9]{9}$') "
            "AND (psgc_city_code IS NULL OR psgc_city_code ~ '^[0-9]{9}$') "
            "AND (psgc_barangay_code IS NULL OR psgc_barangay_code ~ '^[0-9]{9}$')",
            name="chk_companies_psgc_codes",
        ),
        {"schema": "core", "comment": "Legal employers/entities processed independently for HR and payroll."},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    company_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(30))
    registration_no: Mapped[str | None] = mapped_column(String(50))
    timezone: Mapped[str] = mapped_column(String(50), server_default=text("'Asia/Manila'"), nullable=False)
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(100))
    psgc_region_code: Mapped[str | None] = mapped_column(String(9))
    psgc_province_code: Mapped[str | None] = mapped_column(String(9))
    psgc_city_code: Mapped[str | None] = mapped_column(String(9))
    psgc_barangay_code: Mapped[str | None] = mapped_column(String(9))
    barangay: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    province: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    default_currency: Mapped[str] = mapped_column(CHAR(3), server_default=text("'PHP'"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'ACTIVE'"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    locations: Mapped[list["Location"]] = relationship(back_populates="company")