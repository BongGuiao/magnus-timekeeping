from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HolidayModel(Base):
    __tablename__ = "holidays"
    __table_args__ = (
        CheckConstraint(
            "holiday_type IN ('REGULAR', 'SPECIAL_NONWORKING', 'SPECIAL_WORKING', 'LOCAL', 'COMPANY')",
            name="ck_holidays_holiday_type",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'CANCELLED', 'SUPERSEDED')",
            name="ck_holidays_status",
        ),
        CheckConstraint(
            "(psgc_region_code IS NULL OR psgc_region_code ~ '^[0-9]{9}$') "
            "AND (psgc_province_code IS NULL OR psgc_province_code ~ '^[0-9]{9}$') "
            "AND (psgc_city_code IS NULL OR psgc_city_code ~ '^[0-9]{9}$')",
            name="ck_holidays_psgc_codes",
        ),
        CheckConstraint(
            "ncr_district IS NULL OR ncr_district IN "
            "('NCR_1ST_DISTRICT', 'NCR_2ND_DISTRICT', 'NCR_3RD_DISTRICT', 'NCR_4TH_DISTRICT')",
            name="ck_holidays_ncr_district",
        ),
        Index(
            "uq_holidays_calendar_date_name_scope",
            "holiday_calendar_id",
            "holiday_date",
            "holiday_name",
            text("CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_region_code, upper(btrim(region)), '') ELSE '' END"),
            text("CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_province_code, upper(btrim(province)), '') ELSE '' END"),
            text("CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(psgc_city_code, upper(btrim(city)), '') ELSE '' END"),
            text("CASE WHEN holiday_type = 'LOCAL' THEN COALESCE(ncr_district, '') ELSE '' END"),
            unique=True,
        ),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    holiday_calendar_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.holiday_calendars.id"),
        nullable=False,
    )
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    holiday_name: Mapped[str] = mapped_column(String(150), nullable=False)
    holiday_type: Mapped[str] = mapped_column(String(30), nullable=False)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    psgc_region_code: Mapped[str | None] = mapped_column(String(9), nullable=True)
    psgc_province_code: Mapped[str | None] = mapped_column(String(9), nullable=True)
    psgc_city_code: Mapped[str | None] = mapped_column(String(9), nullable=True)
    ncr_district: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_double_holiday: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    pay_rule_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    row_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
